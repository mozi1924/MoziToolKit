"""
Resource pack preferences PropertyGroup, UIList, tier ordering, and management operators.

Pack type is inferred from archive **content** (``utils.pack_detect``) rather than from the file
name. Detection runs on a short debounce timer plus a worker thread so a 30k-entry vanilla client
JAR never stalls the UI, and the result is applied on the main thread. ``pack_type_source`` keeps
manual user corrections authoritative: auto-detection never overwrites a MANUAL tier choice.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

try:
    from ..utils.config import get_config_manager
    from ..utils.system import get_prefs
    from ..utils.pack_detect import (
        KIND_DATA_PACK,
        KIND_LABELS,
        KIND_MOD,
        KIND_MODPACK,
        KIND_RESOURCE_PACK,
        KIND_UNKNOWN,
        KIND_VANILLA_CLIENT,
        KIND_VANILLA_SERVER,
        TYPE_SOURCE_AUTO,
        TYPE_SOURCE_MANUAL,
        PackProbe,
        detect_pack_kind,
        invalidate_pack_probe,
        peek_cached_probe,
        resolve_pack_type,
    )
except (ImportError, ValueError):
    from utils.config import get_config_manager
    from utils.system import get_prefs
    from utils.pack_detect import (
        KIND_DATA_PACK,
        KIND_LABELS,
        KIND_MOD,
        KIND_MODPACK,
        KIND_RESOURCE_PACK,
        KIND_UNKNOWN,
        KIND_VANILLA_CLIENT,
        KIND_VANILLA_SERVER,
        TYPE_SOURCE_AUTO,
        TYPE_SOURCE_MANUAL,
        PackProbe,
        detect_pack_kind,
        invalidate_pack_probe,
        peek_cached_probe,
        resolve_pack_type,
    )

try:
    from .preferences_utils import _safe_get_prefs, refresh_ui_and_menus
except (ImportError, ValueError):
    from ui.preferences_utils import _safe_get_prefs, refresh_ui_and_menus

try:
    from ..i18n import tr
except (ImportError, ValueError):
    from i18n import tr

logger = logging.getLogger("MoziToolKit.UI.PreferencesPacks")

#: Debounce before probing, so typing a path does not open the archive on every keystroke.
PROBE_DEBOUNCE_SECONDS = 0.15
#: Timer cadence while probes are scheduled or in flight.
PROBE_TICK_SECONDS = 0.1
#: Give up waiting on a wedged probe (slow network share) and allow a retry.
PROBE_TIMEOUT_SECONDS = 10.0

_KIND_ICONS = {
    KIND_VANILLA_CLIENT: "WORLD_DATA",
    KIND_VANILLA_SERVER: "WORLD_DATA",
    KIND_MOD: "MODIFIER",
    KIND_RESOURCE_PACK: "PACKAGE",
    KIND_DATA_PACK: "FILE",
    KIND_MODPACK: "FILE_ARCHIVE",
    KIND_UNKNOWN: "QUESTION",
}

_probe_lock = threading.Lock()
_probe_scheduled: Dict[str, float] = {}
_probe_inflight: Dict[str, float] = {}
_probe_results: "queue.Queue[Tuple[str, PackProbe]]" = queue.Queue()


# ---------------------------------------------------------------------------
# Update-callback guards
# ---------------------------------------------------------------------------


#: Fallback guard storage for hosts without ``bpy.types.WindowManager`` (headless tests).
_GUARD_FALLBACK = {"reordering": False, "probing": False}


def _guard_host():
    return getattr(getattr(bpy, "types", None), "WindowManager", None)


def _get_is_reordering() -> bool:
    host = _guard_host()
    if host is None:
        return _GUARD_FALLBACK["reordering"]
    return bool(getattr(host, "_mozi_is_reordering_packs", False))


def _set_is_reordering(val: bool) -> None:
    host = _guard_host()
    if host is None:
        _GUARD_FALLBACK["reordering"] = bool(val)
    else:
        setattr(host, "_mozi_is_reordering_packs", bool(val))


def _is_probing() -> bool:
    host = _guard_host()
    if host is None:
        return _GUARD_FALLBACK["probing"]
    return bool(getattr(host, "_mozi_is_probing_pack", False))


def _set_is_probing(val: bool) -> None:
    host = _guard_host()
    if host is None:
        _GUARD_FALLBACK["probing"] = bool(val)
    else:
        setattr(host, "_mozi_is_probing_pack", bool(val))


def _callbacks_suppressed() -> bool:
    if _get_is_reordering() or _is_probing():
        return True
    try:
        return bool(get_config_manager().is_syncing())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------


def _stem_title(raw_path: str) -> str:
    try:
        return Path(raw_path).stem.replace("_", " ").replace("-", " ").title()
    except Exception:
        return "Resource Pack"


def _looks_auto_named(current_name: str, raw_path: str) -> bool:
    """True when the display name was never customized by the user."""
    name = (current_name or "").strip()
    if not name or name.startswith("Resource Pack") or name == "New Resource Pack":
        return True
    return name == _stem_title(raw_path)


def _auto_name_for(raw_path: str, probe: Optional[PackProbe]) -> Optional[str]:
    """Derive a friendlier name from detected metadata (version string / mod display name)."""
    if probe is None:
        return None
    if probe.kind == KIND_VANILLA_CLIENT and probe.details.get("mc_version"):
        return f"Minecraft {probe.details['mc_version']}"
    if probe.kind == KIND_VANILLA_SERVER and probe.details.get("mc_version"):
        return f"Minecraft Server {probe.details['mc_version']}"
    if probe.kind == KIND_MOD and probe.details.get("mod_name"):
        return str(probe.details["mod_name"])
    return None


# ---------------------------------------------------------------------------
# Detection application (pure-ish, unit-testable)
# ---------------------------------------------------------------------------


def apply_probe_to_entry(item: Any, probe: Optional[PackProbe]) -> bool:
    """
    Write a probe verdict onto a pack entry. Returns True when anything changed.

    Manual type choices are preserved; only the recorded ``detected_kind`` is refreshed.
    """
    if item is None or probe is None:
        return False

    was_probing = _is_probing()
    _set_is_probing(True)
    try:
        return _apply_probe_fields(item, probe)
    finally:
        _set_is_probing(was_probing)


def _apply_probe_fields(item: Any, probe: PackProbe) -> bool:
    changed = False
    source = getattr(item, "pack_type_source", TYPE_SOURCE_AUTO) or TYPE_SOURCE_AUTO
    current_type = getattr(item, "pack_type", "RESOURCE_PACK")

    if getattr(item, "detected_kind", "") != probe.kind:
        setattr(item, "detected_kind", probe.kind)
        changed = True

    resolved_type = resolve_pack_type(current_type, source, probe)
    if resolved_type != current_type:
        setattr(item, "pack_type", resolved_type)
        changed = True

    raw_path = (getattr(item, "path", "") or "").strip()
    if raw_path and _looks_auto_named(getattr(item, "name", ""), raw_path):
        better_name = _auto_name_for(raw_path, probe)
        if better_name and better_name != getattr(item, "name", ""):
            setattr(item, "name", better_name)
            changed = True
    return changed


def probe_entry_now(item: Any) -> Optional[PackProbe]:
    """Detect synchronously and apply to one entry (used by the explicit re-detect operator)."""
    raw_path = (getattr(item, "path", "") or "").strip()
    if not raw_path:
        return None
    invalidate_pack_probe(raw_path)
    probe = detect_pack_kind(raw_path)
    apply_probe_to_entry(item, probe)
    return probe


# ---------------------------------------------------------------------------
# Background probe pipeline
# ---------------------------------------------------------------------------


def _timers_available() -> bool:
    try:
        timers = bpy.app.timers
        if type(timers).__module__.startswith("unittest.mock"):
            return False
        return hasattr(timers, "register") and hasattr(timers, "is_registered")
    except Exception:
        return False


def _probe_worker(key: str) -> None:
    try:
        probe = detect_pack_kind(key)
    except Exception as exc:  # defensive: never kill the worker with an exception
        logger.warning("pack probe failed for %s: %s", key, exc)
        probe = PackProbe(error=f"{type(exc).__name__}: {exc}")
    # Publish before clearing the inflight flag: the timer must never observe "queue empty and
    # nothing in flight" in the window between the two, or the result would be dropped.
    _probe_results.put((key, probe))
    with _probe_lock:
        _probe_inflight.pop(key, None)


def _start_probe(key: str) -> None:
    with _probe_lock:
        if key in _probe_inflight:
            return
        _probe_inflight[key] = time.monotonic()
    threading.Thread(target=_probe_worker, args=(key,), name="MTK-PackProbe", daemon=True).start()


def schedule_pack_probe(raw_path: str) -> None:
    """Debounce + schedule a content probe for *raw_path* (never blocks the caller)."""
    key = (raw_path or "").strip()
    if not key:
        return
    if not _timers_available():
        # Non-Blender host (tests, mock runs): probe and apply synchronously.
        _apply_probe_result(key, detect_pack_kind(key))
        return
    with _probe_lock:
        _probe_scheduled[key] = time.monotonic() + PROBE_DEBOUNCE_SECONDS
    try:
        if not bpy.app.timers.is_registered(_pack_probe_tick):
            bpy.app.timers.register(_pack_probe_tick, first_interval=PROBE_TICK_SECONDS)
    except Exception:
        logger.debug("failed to register pack probe timer", exc_info=True)


def _apply_probe_result(key: str, probe: PackProbe) -> bool:
    """Apply one finished probe on the main thread. Returns True when anything changed."""
    context = getattr(bpy, "context", None)
    prefs = _safe_get_prefs(context)
    if prefs is None:
        return False
    changed = False
    for item in getattr(prefs, "resource_packs", []):
        if (getattr(item, "path", "") or "").strip() != key:
            continue
        if apply_probe_to_entry(item, probe):
            changed = True
    if changed:
        reorder_resource_packs_by_tier(prefs)
        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)
    return changed


def schedule_pending_pack_detection(prefs) -> int:
    """
    Queue content probes for entries that never got a verdict (config migration / first run).

    Called once per session from the preferences panel; every probe is debounced and runs off the
    main thread, so opening the panel never stalls on a stack of large JARs.
    """
    if prefs is None:
        return 0
    scheduled = 0
    try:
        items = list(getattr(prefs, "resource_packs", []))
    except TypeError:
        return 0
    for item in items:
        if getattr(item, "pack_type_source", TYPE_SOURCE_AUTO) != TYPE_SOURCE_AUTO:
            continue
        if (getattr(item, "detected_kind", "") or "").strip():
            continue
        raw = (getattr(item, "path", "") or "").strip()
        if not raw or not Path(raw).exists():
            continue
        schedule_pack_probe(raw)
        scheduled += 1
    return scheduled


def _drain_probe_results() -> bool:
    """Drain the worker queue. Returns True when anything changed."""
    changed_any = False
    while True:
        try:
            key, probe = _probe_results.get_nowait()
        except queue.Empty:
            return changed_any
        if _apply_probe_result(key, probe):
            changed_any = True


def _pack_probe_tick() -> Optional[float]:
    """Main-thread timer: dispatch due probes and apply finished ones."""
    try:
        _drain_probe_results()
        now = time.monotonic()
        due: list = []
        with _probe_lock:
            for key, deadline in list(_probe_scheduled.items()):
                if deadline <= now:
                    _probe_scheduled.pop(key, None)
                    due.append(key)
            for key, started in list(_probe_inflight.items()):
                if now - started > PROBE_TIMEOUT_SECONDS:
                    _probe_inflight.pop(key, None)
                    logger.warning("pack probe timed out for %s", key)
        for key in due:
            if os.path.exists(key):
                _start_probe(key)
        with _probe_lock:
            busy = bool(_probe_scheduled or _probe_inflight)
    except Exception:
        logger.warning("pack probe timer error", exc_info=True)
        return None
    return PROBE_TICK_SECONDS if busy or not _probe_results.empty() else None


# ---------------------------------------------------------------------------
# Tier ordering
# ---------------------------------------------------------------------------


def reorder_resource_packs_by_tier(prefs):
    """
    Sorts prefs.resource_packs CollectionProperty into three strict tiers:
    1. RESOURCE_PACK (top)
    2. MOD_JAR (middle)
    3. VANILLA (bottom)
    Preserves existing relative order within each tier using stable in-place moves.
    """
    if _get_is_reordering() or get_config_manager().is_syncing():
        return
    if prefs is None or not hasattr(prefs, "resource_packs") or len(prefs.resource_packs) <= 1:
        return

    def tier_key(item):
        pt = getattr(item, "pack_type", "RESOURCE_PACK")
        if pt == "RESOURCE_PACK":
            return 0
        elif pt == "MOD_JAR":
            return 1
        else:  # VANILLA
            return 2

    _set_is_reordering(True)
    try:
        n = len(prefs.resource_packs)
        for i in range(1, n):
            j = i
            while j > 0 and tier_key(prefs.resource_packs[j]) < tier_key(prefs.resource_packs[j - 1]):
                prefs.resource_packs.move(j, j - 1)
                j -= 1
    finally:
        _set_is_reordering(False)


# ---------------------------------------------------------------------------
# Property update callbacks
# ---------------------------------------------------------------------------


def on_pack_entry_changed(self, context):
    """Callback when a resource pack entry's attributes change."""
    if _callbacks_suppressed():
        return
    prefs = _safe_get_prefs(self)
    if prefs:
        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)
        try:
            from ..bridge.assets import invalidate_asset_cache_memory
            from ..bridge.world import clear_world_sessions

            invalidate_asset_cache_memory()
            clear_world_sessions()
        except Exception:
            try:
                from bridge.assets import invalidate_asset_cache_memory
                from bridge.world import clear_world_sessions

                invalidate_asset_cache_memory()
                clear_world_sessions()
            except Exception:
                pass


def on_pack_type_changed(self, context):
    """Callback when a resource pack entry's pack_type tier changes."""
    if _callbacks_suppressed():
        return
    # A human picking a tier from the dropdown makes that choice authoritative.
    _set_is_probing(True)
    try:
        if getattr(self, "pack_type_source", TYPE_SOURCE_AUTO) != TYPE_SOURCE_MANUAL:
            self.pack_type_source = TYPE_SOURCE_MANUAL
    finally:
        _set_is_probing(False)

    prefs = _safe_get_prefs(self)
    if prefs:
        reorder_resource_packs_by_tier(prefs)
        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)


def on_pack_type_source_changed(self, context):
    """Callback when the user switches between AUTO and MANUAL type resolution."""
    if _callbacks_suppressed():
        return
    if getattr(self, "pack_type_source", TYPE_SOURCE_AUTO) == TYPE_SOURCE_AUTO:
        raw = (getattr(self, "path", "") or "").strip()
        if raw:
            invalidate_pack_probe(raw)
            if Path(raw).exists():
                schedule_pack_probe(raw)
    prefs = _safe_get_prefs(self)
    if prefs:
        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)


def on_pack_path_changed(self, context):
    """Auto-fill the display name and schedule content-based pack type detection."""
    if _callbacks_suppressed():
        return
    try:
        raw = (self.path or "").strip()
        if raw and Path(raw).exists():
            if _looks_auto_named(self.name, raw):
                self.name = _stem_title(raw)
            if getattr(self, "pack_type_source", TYPE_SOURCE_AUTO) == TYPE_SOURCE_AUTO:
                schedule_pack_probe(raw)
    except Exception:
        pass
    prefs = _safe_get_prefs(self)
    if prefs:
        reorder_resource_packs_by_tier(prefs)
        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)


# ---------------------------------------------------------------------------
# Detection presentation helpers (no I/O: cache lookups only)
# ---------------------------------------------------------------------------


def describe_detected_kind(item: Any) -> Tuple[str, str]:
    """Return ``(label, icon)`` describing the last content-detection verdict."""
    kind = (getattr(item, "detected_kind", "") or "").strip()
    if not kind:
        return tr("Not detected yet"), "INFO"
    label = tr(KIND_LABELS.get(kind, kind))
    probe = peek_cached_probe((getattr(item, "path", "") or "").strip())
    if probe is not None and probe.kind == kind and probe.kind != KIND_UNKNOWN:
        label = f"{label}  ({probe.confidence * 100:.0f}%)"
    return label, _KIND_ICONS.get(kind, "INFO")


def detected_kind_warning(item: Any) -> Optional[str]:
    """Return a user-facing warning when the detected archive cannot feed the bake pipeline."""
    kind = (getattr(item, "detected_kind", "") or "").strip()
    if kind in {KIND_DATA_PACK, KIND_MODPACK}:
        return tr("This archive provides no textures for baking (data pack / modpack).")
    probe = peek_cached_probe((getattr(item, "path", "") or "").strip())
    if probe is not None and probe.details.get("archive_root"):
        return tr("Pack is nested inside a folder; Minecraft will not load it as-is.")
    return None


# ---------------------------------------------------------------------------
# Property group / UI list
# ---------------------------------------------------------------------------


class MOZI_PG_resource_pack_entry(bpy.types.PropertyGroup):
    __slots__ = ()

    name: StringProperty(
        name="Name",
        description="Display name for this pack/JAR",
        default="New Resource Pack",
        update=on_pack_entry_changed,
    )
    path: StringProperty(
        name="Path",
        description="File path to .zip/.jar archive or extracted directory",
        subtype="FILE_PATH",
        default="",
        update=on_pack_path_changed,
    )
    enabled: BoolProperty(
        name="Enabled",
        description="Enable this pack in the fallback resolution stack",
        default=True,
        update=on_pack_entry_changed,
    )
    pack_type: EnumProperty(
        name="Pack Type",
        description="Classification of this asset source",
        items=[
            ("RESOURCE_PACK", "Resource Pack", "Standard ZIP or folder resource pack (Overrides base assets)"),
            ("MOD_JAR", "Mod JAR", "Mod JAR archive (Fabric/Forge/NeoForge) containing assets"),
            ("VANILLA", "Vanilla JAR", "Minecraft vanilla client or server JAR archive (Base foundation)"),
        ],
        default="RESOURCE_PACK",
        update=on_pack_type_changed,
    )
    pack_type_source: EnumProperty(
        name="Type Source",
        description="AUTO classifies the archive content and may update the type; MANUAL keeps your choice",
        items=[
            ("AUTO", "Auto", "Detect the pack type from archive content and keep it in sync"),
            ("MANUAL", "Manual", "Keep the pack type exactly as selected, ignoring auto-detection"),
        ],
        default=TYPE_SOURCE_AUTO,
        update=on_pack_type_source_changed,
    )
    detected_kind: StringProperty(
        name="Detected Kind",
        description="Last content-detection verdict (Vanilla Client, Mod, Resource Pack, ...)",
        default="",
    )


class MOZI_UL_resource_packs_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.prop(item, "enabled", text="", emboss=False)
            _tr = tr

            if item.pack_type == "VANILLA":
                icon_type = "WORLD_DATA"
                tier_badge = _tr("Vanilla Base")
            elif item.pack_type == "MOD_JAR":
                icon_type = "MODIFIER"
                mod_idx = sum(1 for i, elem in enumerate(data.resource_packs) if elem.pack_type == "MOD_JAR" and i <= index)
                tier_badge = f"{_tr('Mod')} #{mod_idx}"
            else:
                icon_type = "PACKAGE"
                rp_idx = sum(1 for i, elem in enumerate(data.resource_packs) if elem.pack_type == "RESOURCE_PACK" and i <= index)
                tier_badge = f"{_tr('RP')} #{rp_idx}"

            is_valid = bool(item.path and Path(item.path).exists())
            name_text = item.name or (Path(item.path).stem if item.path else "Unnamed Pack")

            if not is_valid and item.path:
                row.label(text=f"{name_text} {_tr('(Missing File)')}", icon="ERROR")
            elif not item.path:
                row.label(text=f"{name_text} {_tr('(No Path)')}", icon="QUESTION")
            else:
                row.label(text=name_text, icon=icon_type)

            p_badge = row.row(align=True)
            p_badge.alignment = "RIGHT"
            p_badge.enabled = False
            source_tag = "" if getattr(item, "pack_type_source", TYPE_SOURCE_AUTO) == TYPE_SOURCE_AUTO else f" [{_tr('Manual')}]"
            p_badge.label(text=f"{tier_badge}{source_tag}")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.name, icon="PACKAGE")


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------


def populate_resource_packs(prefs, entries):
    """Safely populate prefs.resource_packs from a list of dicts without reorder race conditions."""
    if prefs is None:
        return
    _set_is_reordering(True)
    try:
        setattr(prefs, "_mozi_is_syncing", True)
        prefs.resource_packs.clear()
        for p_item in entries:
            if isinstance(p_item, dict):
                p_elem = prefs.resource_packs.add()
                p_elem.name = p_item.get("name", "Resource Pack")
                p_elem.path = p_item.get("path", "")
                p_elem.enabled = p_item.get("enabled", True)
                p_elem.pack_type = p_item.get("pack_type", "RESOURCE_PACK")
                if hasattr(p_elem, "pack_type_source"):
                    p_elem.pack_type_source = p_item.get("pack_type_source", TYPE_SOURCE_AUTO)
                if hasattr(p_elem, "detected_kind"):
                    p_elem.detected_kind = p_item.get("detected_kind", "")
    finally:
        setattr(prefs, "_mozi_is_syncing", False)
        _set_is_reordering(False)

    reorder_resource_packs_by_tier(prefs)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------


class MOZI_OT_pack_add(bpy.types.Operator):
    """Add a new resource pack or Minecraft/Mod JAR entry to the fallback stack"""

    bl_idname = "mozi.pack_add"
    bl_label = "Add Pack or JAR"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = _safe_get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}
        if not getattr(prefs, "is_initialized", False):
            get_config_manager().sync_to_preferences(prefs)

        _set_is_probing(True)
        try:
            coll = prefs.resource_packs
            elem = coll.add()
            elem.name = f"Resource Pack #{len(coll)}"
            elem.enabled = True
            elem.pack_type = "RESOURCE_PACK"
            if hasattr(elem, "pack_type_source"):
                elem.pack_type_source = TYPE_SOURCE_AUTO
            if hasattr(elem, "detected_kind"):
                elem.detected_kind = ""
            # New packs enter at the very top of the stack (highest resolution priority),
            # matching Minecraft's "newly added pack overrides everything below it" model.
            if len(coll) > 1:
                coll.move(len(coll) - 1, 0)
        finally:
            _set_is_probing(False)
        reorder_resource_packs_by_tier(prefs)
        prefs.resource_packs_index = 0

        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)
        return {"FINISHED"}


class MOZI_OT_pack_remove(bpy.types.Operator):
    """Remove selected pack from the fallback stack"""

    bl_idname = "mozi.pack_remove"
    bl_label = "Remove Pack or JAR"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = _safe_get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}
        idx = prefs.resource_packs_index
        if 0 <= idx < len(prefs.resource_packs):
            prefs.resource_packs.remove(idx)
            reorder_resource_packs_by_tier(prefs)
            prefs.resource_packs_index = max(0, min(idx, len(prefs.resource_packs) - 1))
            get_config_manager().sync_from_preferences(prefs)
            refresh_ui_and_menus(context)
        return {"FINISHED"}


class MOZI_OT_pack_move(bpy.types.Operator):
    """Move selected pack up or down to adjust resolution priority within its tier"""

    bl_idname = "mozi.pack_move"
    bl_label = "Move Pack Priority"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        items=[("UP", "Up", "Increase Priority"), ("DOWN", "Down", "Decrease Priority")],
        default="UP",
    )

    def execute(self, context):
        prefs = _safe_get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}
        idx = prefs.resource_packs_index
        if not (0 <= idx < len(prefs.resource_packs)):
            return {"CANCELLED"}

        curr_item = prefs.resource_packs[idx]
        curr_tier = curr_item.pack_type

        if self.direction == "UP" and idx > 0:
            target_item = prefs.resource_packs[idx - 1]
            if target_item.pack_type != curr_tier:
                self.report({'INFO'}, f"Cannot move {curr_tier.replace('_', ' ').title()} above {target_item.pack_type.replace('_', ' ').title()} tier.")
                return {"CANCELLED"}
            prefs.resource_packs.move(idx, idx - 1)
            prefs.resource_packs_index = idx - 1
            get_config_manager().sync_from_preferences(prefs)
            refresh_ui_and_menus(context)
        elif self.direction == "DOWN" and idx < len(prefs.resource_packs) - 1:
            target_item = prefs.resource_packs[idx + 1]
            if target_item.pack_type != curr_tier:
                self.report({'INFO'}, f"Cannot move {curr_tier.replace('_', ' ').title()} below {target_item.pack_type.replace('_', ' ').title()} tier.")
                return {"CANCELLED"}
            prefs.resource_packs.move(idx, idx + 1)
            prefs.resource_packs_index = idx + 1
            get_config_manager().sync_from_preferences(prefs)
            refresh_ui_and_menus(context)
        return {"FINISHED"}


class MOZI_OT_pack_detect(bpy.types.Operator):
    """Re-scan this archive and let MoziToolKit classify its pack type from its contents"""

    bl_idname = "mozi.pack_detect"
    bl_label = "Re-detect Pack Type"
    bl_description = "Inspect the selected .jar/.zip/folder content and choose its pack type automatically"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = _safe_get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}
        idx = prefs.resource_packs_index
        if not (0 <= idx < len(prefs.resource_packs)):
            return {"CANCELLED"}

        item = prefs.resource_packs[idx]
        raw = (item.path or "").strip()
        if not raw or not Path(raw).exists():
            self.report({'ERROR'}, "Select an existing .jar/.zip archive or pack folder first")
            return {"CANCELLED"}

        _set_is_probing(True)
        try:
            if hasattr(item, "pack_type_source"):
                item.pack_type_source = TYPE_SOURCE_AUTO
        finally:
            _set_is_probing(False)

        probe = probe_entry_now(item)

        reorder_resource_packs_by_tier(prefs)
        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)

        if probe is None:
            self.report({'WARNING'}, "Detection did not run")
            return {"CANCELLED"}
        if not probe.is_known:
            self.report({'WARNING'}, f"Could not identify this archive ({probe.error or 'no signature matched'})")
            return {"FINISHED"}
        self.report({'INFO'}, f"Detected {probe.label()} ({probe.confidence * 100:.0f}% confidence)")
        return {"FINISHED"}


PACKS_CLASSES = (
    MOZI_PG_resource_pack_entry,
    MOZI_UL_resource_packs_list,
    MOZI_OT_pack_add,
    MOZI_OT_pack_remove,
    MOZI_OT_pack_move,
    MOZI_OT_pack_detect,
)
