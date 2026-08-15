"""
Progress Protocol Module for MoziToolKit Pipeline.

Defines the ProgressUpdate data structure used for reporting fine-grained
progress and status updates across pipeline steps and modal UI runners.
"""

from dataclasses import dataclass


@dataclass
class ProgressUpdate:
    """Represents a fine-grained progress update with normalized fraction."""

    current: float
    total: float
    message: str = ""
    fraction: float = 0.0

    def __post_init__(self):
        if self.total > 0:
            self.fraction = max(0.0, min(1.0, float(self.current) / float(self.total)))
        else:
            self.fraction = 0.0
