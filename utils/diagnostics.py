"""
Host-side execution profile aggregation.

Collects per-stage timings coming from the Rust `ExecutionProfile` plus
host-side stages, and keeps the most recent operation for UI/diagnostics.
Deliberately dependency-free so the bridge layer can use it without importing
the dev/debug package (which is excluded from release builds).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

_LAST_PROFILE: Optional[Dict[str, Any]] = None
_LOCK = threading.Lock()


def _make_stage(name: Any, duration_ms: Any, items_count: Any) -> Dict[str, Any]:
    return {
        "name": str(name),
        "duration_ms": round(float(duration_ms or 0.0), 3),
        "items_count": items_count,
        "percent": 0.0,
    }


def _recalculate(profile: Dict[str, Any], measured_total_ms: float) -> None:
    """Recompute percentages and the stage count.

    ``measured_total_ms`` is authoritative (it includes uninstrumented time from
    Rust), but never below the sum of the stages so percentages stay <= 100.
    """
    stages = profile.get("stages", [])
    stage_sum = sum(float(stage.get("duration_ms", 0.0)) for stage in stages)
    total_ms = max(float(measured_total_ms or 0.0), stage_sum)
    for stage in stages:
        duration = float(stage.get("duration_ms", 0.0))
        stage["percent"] = round((duration / total_ms) * 100.0, 1) if total_ms > 0 else 0.0
    profile["total_ms"] = round(total_ms, 3)
    profile["stage_count"] = len(stages)


def record_operation_profile(
    operation_name: str,
    profile_obj: Any,
    host_stages: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Records an execution profile snapshot from Rust or Python with optional host stages."""
    global _LAST_PROFILE
    if profile_obj is None and not host_stages:
        return

    stages: List[Dict[str, Any]] = []
    measured_total_ms = 0.0

    if hasattr(profile_obj, "stages"):
        measured_total_ms = float(getattr(profile_obj, "total_duration_ms", 0.0) or 0.0)
        for stage in profile_obj.stages:
            stages.append(
                _make_stage(
                    getattr(stage, "name", "stage"),
                    getattr(stage, "duration_ms", 0.0),
                    getattr(stage, "items_count", None),
                )
            )
    elif isinstance(profile_obj, dict):
        measured_total_ms = float(
            profile_obj.get("total_duration_ms", profile_obj.get("total_ms", 0.0)) or 0.0
        )
        for stage in profile_obj.get("stages", []):
            stages.append(
                _make_stage(
                    stage.get("name", "stage"),
                    stage.get("duration_ms", 0.0),
                    stage.get("items_count"),
                )
            )

    host_total_ms = 0.0
    for host_stage in host_stages or []:
        duration = float(host_stage.get("duration_ms", 0.0) or 0.0)
        host_total_ms += duration
        stages.append(
            _make_stage(
                host_stage.get("name", "host_stage"),
                duration,
                host_stage.get("items_count"),
            )
        )

    new_profile: Dict[str, Any] = {
        "operation": str(operation_name),
        "total_ms": 0.0,
        "stage_count": len(stages),
        "stages": stages,
        "timestamp": time.strftime("%H:%M:%S"),
    }
    _recalculate(new_profile, measured_total_ms + host_total_ms)
    with _LOCK:
        _LAST_PROFILE = new_profile


def append_stage_to_last_profile(
    name: str,
    duration_ms: float,
    items_count: Optional[int] = None,
) -> None:
    """Appends a host-side stage to the currently active profile (e.g. Blender injection)."""
    global _LAST_PROFILE
    with _LOCK:
        if _LAST_PROFILE is None:
            _LAST_PROFILE = {
                "operation": "Host Operation",
                "total_ms": 0.0,
                "stage_count": 0,
                "stages": [],
                "timestamp": time.strftime("%H:%M:%S"),
            }
        duration = float(duration_ms or 0.0)
        _LAST_PROFILE["stages"].append(_make_stage(name, duration, items_count))
        _recalculate(
            _LAST_PROFILE,
            float(_LAST_PROFILE.get("total_ms", 0.0)) + duration,
        )


def get_last_profile() -> Optional[Dict[str, Any]]:
    """Returns the most recent execution profile, if any."""
    return _LAST_PROFILE


def clear_last_profile() -> None:
    """Clears the cached profile."""
    global _LAST_PROFILE
    with _LOCK:
        _LAST_PROFILE = None


__all__ = [
    "record_operation_profile",
    "append_stage_to_last_profile",
    "get_last_profile",
    "clear_last_profile",
]
