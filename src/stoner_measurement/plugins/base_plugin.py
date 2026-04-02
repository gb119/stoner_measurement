"""Abstract base class for all measurement plugins.

A plugin must:

1. Inherit from :class:`BasePlugin`.
2. Override :attr:`name` to provide a unique string identifier.
3. Implement :meth:`execute` to yield ``(x, y)`` data pairs.
4. Optionally override :meth:`config_widget` to supply a configuration
   :class:`~PyQt6.QtWidgets.QWidget` that will appear as a tab in the
   right-hand panel.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generator

from PyQt6.QtWidgets import QLabel, QWidget


class BasePlugin(ABC):
    """Abstract base class for measurement plugins.

    Subclasses must implement :attr:`name` and :meth:`execute`.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique human-readable name for this plugin."""

    @abstractmethod
    def execute(
        self, parameters: dict[str, Any]
    ) -> Generator[tuple[float, float], None, None]:
        """Execute the measurement step described by *parameters*.

        Yields
        ------
        tuple[float, float]
            ``(x, y)`` data points produced by the step.

        Parameters
        ----------
        parameters:
            Step-specific configuration provided by the user.
        """

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a :class:`QWidget` for configuring this plugin.

        The default implementation returns a simple label.  Override
        this method to provide a richer configuration interface.

        Parameters
        ----------
        parent:
            Optional Qt parent widget.
        """
        label = QLabel(f"<i>No configuration available for <b>{self.name}</b></i>")
        label.setParent(parent)
        return label
