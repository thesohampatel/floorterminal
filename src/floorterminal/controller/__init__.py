"""Application controller split into cohesive, separately reviewable layers.

``FloorTerminalApp`` composes these mixins. They are kept as mixins rather than
collaborators so the split changes only how the code is organised for review,
never how it behaves at runtime.
"""

from __future__ import annotations

from .dialogs import DialogMixin
from .updates import SoftwareUpdateMixin
from .workflow import WorkflowMixin

__all__ = ["DialogMixin", "SoftwareUpdateMixin", "WorkflowMixin"]
