"""
Pipeline Context Module for MoziToolKit

Holds state, target objects, parameters, shared data, and reports
across sequential execution of pipeline steps.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
import bpy
from .progress import ProgressUpdate


class PipelineContext:
    """Carries runtime execution context between pipeline steps."""

    def __init__(
        self,
        context: bpy.types.Context,
        params: Optional[Dict[str, Any]] = None,
        target_objects: Optional[List[bpy.types.Object]] = None,
        progress_callback: Optional[Callable[[ProgressUpdate], None]] = None,
    ):
        self.context: bpy.types.Context = context
        self.params: Dict[str, Any] = params or {}
        self.data: Dict[str, Any] = {}
        self.reports: List[Tuple[str, str]] = []
        self.is_cancelled: bool = False
        self.progress_callback: Optional[Callable[[ProgressUpdate], None]] = progress_callback

        if target_objects is not None:
            self.target_objects: List[bpy.types.Object] = target_objects
        else:
            selected = getattr(context, "selected_objects", None) or []
            active = getattr(context, "active_object", None)
            if not selected and active:
                selected = [active]
            self.target_objects = [o for o in selected if o and o.type == "MESH"]

    @property
    def active_object(self) -> Optional[bpy.types.Object]:
        if self.context and hasattr(self.context, "active_object"):
            return self.context.active_object
        return self.target_objects[0] if self.target_objects else None

    def get_param(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)

    def set_param(self, key: str, value: Any) -> None:
        self.params[key] = value

    def get_data(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set_data(self, key: str, value: Any) -> None:
        self.data[key] = value

    def report(self, level: str, message: str) -> None:
        """Log a status report message ('INFO', 'WARNING', 'ERROR')."""
        self.reports.append((level, message))

    def update_progress(self, current: float, total: float, message: str = "") -> ProgressUpdate:
        """Notify the registered progress callback with current progress."""
        update = ProgressUpdate(current=current, total=total, message=message)
        if self.progress_callback:
            self.progress_callback(update)
        return update
