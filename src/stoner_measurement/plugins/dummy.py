"""Dummy plugin — ships with the package for demonstration and testing.

The :class:`DummyPlugin` generates a simple linear ramp of data points.
It requires no hardware and is useful as a smoke-test.
"""

from __future__ import annotations

import math
from collections.abc import Generator
from typing import Any

from PyQt6.QtWidgets import (
    QFormLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

from stoner_measurement.plugins.trace import TracePlugin


class DummyPlugin(TracePlugin):
    """A built-in demo plugin that generates sine-wave data.

    Parameters accepted in ``parameters`` dict
    ------------------------------------------
    points : int
        Number of data points to generate (default 100).
    amplitude : float
        Amplitude of the sine wave (default 1.0).
    """

    @property
    def name(self) -> str:
        """Unique identifier for the dummy plugin."""
        return "Dummy"

    def execute(
        self, parameters: dict[str, Any]
    ) -> Generator[tuple[float, float]]:
        """Yield ``points`` sine-wave data points."""
        points = int(parameters.get("points", 100))
        amplitude = float(parameters.get("amplitude", 1.0))
        for i in range(points):
            x = i / max(points - 1, 1) * 2 * math.pi
            y = amplitude * math.sin(x)
            yield x, y

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a simple form for configuring the dummy plugin."""
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        self._points_spin = QSpinBox()
        self._points_spin.setRange(2, 10_000)
        self._points_spin.setValue(100)
        self._points_spin.setToolTip("Number of data points to generate")

        layout.addRow(QLabel("Points:"), self._points_spin)
        widget.setLayout(layout)
        return widget

    def _plugin_config_tabs(
        self, parent: QWidget | None = None
    ) -> list[tuple[str, QWidget]]:
        """Return the *Settings* and *About* plugin-specific configuration tabs.

        These tabs follow the scan-related tabs provided by
        :class:`~stoner_measurement.plugins.trace.TracePlugin`.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = DummyPlugin()
            >>> tabs = plugin._plugin_config_tabs()
            >>> [t for t, _ in tabs]
            ['Dummy \u2013 Settings', 'Dummy \u2013 About']
        """
        settings_widget = self.config_widget(parent=parent)

        about_widget = QWidget(parent)
        about_layout = QFormLayout(about_widget)
        about_layout.addRow(
            QLabel(
                "<i>Dummy plugin — generates a sine-wave signal for testing.</i>"
            )
        )
        about_widget.setLayout(about_layout)

        return [
            (f"{self.name} \u2013 Settings", settings_widget),
            (f"{self.name} \u2013 About", about_widget),
        ]

    @property
    def configured_points(self) -> int:
        """Return the number of points configured in the UI (if the widget exists)."""
        try:
            return self._points_spin.value()
        except AttributeError:
            return 100
