"""
MoziToolKit Dev Profile Tracker.
Captures and maintains the execution profile of the most recent backend operation
for UI display and diagnostics.
"""

from typing import Any, Dict, List, Optional
import time

_LAST_PROFILE: Optional[Dict[str, Any]] = None


def _recalculate_profile(profile_dict: Dict[str, Any]) -> None:
    """Recalculates total_ms and stage percentages for a profile dict."""
    stages = profile_dict.get("stages", [])
    total_ms = sum(float(s.get("duration_ms", 0.0)) for s in stages)
    for s in stages:
        d_ms = float(s.get("duration_ms", 0.0))
        s["percent"] = round((d_ms / max(0.001, total_ms)) * 100.0, 1) if total_ms > 0 else 0.0
    profile_dict["total_ms"] = round(total_ms, 2)
    profile_dict["stage_count"] = len(stages)


def record_operation_profile(
    operation_name: str,
    profile_obj: Any,
    host_stages: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Records an execution profile snapshot from Rust or Python backend with optional host stages."""
    global _LAST_PROFILE
    if profile_obj is None and not host_stages:
        return

    stages: List[Dict[str, Any]] = []

    if hasattr(profile_obj, "stages"):
        for s in profile_obj.stages:
            stages.append({
                "name": str(s.name),
                "duration_ms": round(float(s.duration_ms), 3),
                "items_count": getattr(s, "items_count", None),
                "percent": 0.0,
            })
    elif isinstance(profile_obj, dict):
        for s in profile_obj.get("stages", []):
            stages.append({
                "name": str(s.get("name", "stage")),
                "duration_ms": round(float(s.get("duration_ms", 0.0)), 3),
                "items_count": s.get("items_count"),
                "percent": 0.0,
            })

    if host_stages:
        for hs in host_stages:
            stages.append({
                "name": str(hs.get("name", "host_stage")),
                "duration_ms": round(float(hs.get("duration_ms", 0.0)), 3),
                "items_count": hs.get("items_count"),
                "percent": 0.0,
            })

    new_profile = {
        "operation": operation_name,
        "total_ms": 0.0,
        "stage_count": len(stages),
        "stages": stages,
        "timestamp": time.strftime("%H:%M:%S"),
    }
    _recalculate_profile(new_profile)
    _LAST_PROFILE = new_profile


def append_stage_to_last_profile(
    name: str,
    duration_ms: float,
    items_count: Optional[int] = None,
) -> None:
    """Appends an execution stage to the currently active profile (e.g. host-side Blender meshing)."""
    global _LAST_PROFILE
    if _LAST_PROFILE is None:
        _LAST_PROFILE = {
            "operation": "Host Operation",
            "total_ms": 0.0,
            "stage_count": 0,
            "stages": [],
            "timestamp": time.strftime("%H:%M:%S"),
        }

    _LAST_PROFILE["stages"].append({
        "name": str(name),
        "duration_ms": round(float(duration_ms), 3),
        "items_count": items_count,
        "percent": 0.0,
    })
    _recalculate_profile(_LAST_PROFILE)


def get_last_profile() -> Optional[Dict[str, Any]]:
    """Returns the most recent execution profile, if any."""
    return _LAST_PROFILE


def clear_last_profile() -> None:
    """Clears the cached profile."""
    global _LAST_PROFILE
    _LAST_PROFILE = None


__all__ = [
    "record_operation_profile",
    "append_stage_to_last_profile",
    "get_last_profile",
    "clear_last_profile",
]
