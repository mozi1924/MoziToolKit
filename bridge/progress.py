"""
MoziToolKit Bridge: Unified Progress Reporting Abstraction.

Provides standardized, host-agnostic dataclasses and callbacks for real-time
progress updates dispatched from native libmtk engines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Union


@dataclass(slots=True)
class ProgressReport:
    """Standard progress milestone payload."""
    stage: str = "progress"
    current: int = 0
    total: int = 0
    message: str = ""
    percent: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProgressReport:
        current = int(data.get("current", 0))
        total = int(data.get("total", 0))
        percent = float(data.get("percent", 0.0))
        if total > 0 and percent == 0.0:
            percent = (current / total) * 100.0
        return cls(
            stage=str(data.get("stage", "progress")),
            current=current,
            total=total,
            message=str(data.get("message", "")),
            percent=percent,
        )


ProgressCallback = Callable[[ProgressReport], None]


def wrap_progress_callback(cb: Optional[Union[ProgressCallback, Callable[[Dict[str, Any]], None]]]) -> Optional[Callable[[Dict[str, Any]], None]]:
    """
    Wraps a ProgressCallback so it can accept either a dict (from PyO3 Rust callback)
    or a ProgressReport instance.
    """
    if cb is None:
        return None

    def _wrapper(payload: Union[Dict[str, Any], ProgressReport]):
        if isinstance(payload, dict):
            report = ProgressReport.from_dict(payload)
            try:
                cb(report)
            except TypeError:
                cb(payload)  # type: ignore
        elif isinstance(payload, ProgressReport):
            cb(payload)

    return _wrapper
