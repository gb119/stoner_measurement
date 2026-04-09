"""Dummy plugin — ships with the package for demonstration and testing.

The :class:`DummyPlugin` generates a sine-wave trace whose x-values are
driven by the active scan generator.  It requires no hardware and is useful
as a smoke-test.
"""

from __future__ import annotations

import math
from collections.abc import Generator
from typing import Any

from stoner_measurement.plugins.trace import TracePlugin, TraceStatus


class DummyPlugin(TracePlugin):
    """A built-in demo plugin that generates sine-wave data.

    Scan points are read from the active
    :attr:`~stoner_measurement.plugins.trace.TracePlugin.scan_generator`.
    Only points flagged for measurement (``measure=True``) are yielded.
    The *y*-value at each scan point *x* is ``amplitude × sin(x)``.

    Keyword Parameters:
        amplitude (float):
            Amplitude of the sine wave passed in the ``parameters`` dict to
            :meth:`execute`.  Defaults to ``1.0``.
    """

    @property
    def name(self) -> str:
        """Unique identifier for the dummy plugin."""
        return "Dummy"

    def connect(self) -> None:
        """Initialise the dummy plugin.

        No real hardware is required; this simply marks the plugin as ready.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = DummyPlugin()
            >>> plugin.connect()
            >>> plugin.status is TraceStatus.IDLE
            True
        """
        self._set_status(TraceStatus.IDLE)

    def execute(
        self, parameters: dict[str, Any]
    ) -> Generator[tuple[float, float]]:
        """Yield sine-wave data points driven by the active scan generator.

        Iterates over the scan generator and yields ``(x, amplitude·sin(x))``
        for every point whose *measure* flag is ``True``.

        Args:
            parameters (dict[str, Any]):
                Step-specific configuration.  Recognised keys:

                * ``"amplitude"`` *(float)* — sine-wave amplitude (default ``1.0``).

        Yields:
            (tuple[float, float]):
                ``(x, y)`` data point pairs.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.scan import SteppedScanGenerator
            >>> plugin = DummyPlugin()
            >>> plugin.scan_generator = SteppedScanGenerator(
            ...     start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
            ... )
            >>> pts = list(plugin.execute({}))
            >>> len(pts)
            5
            >>> isinstance(pts[0], tuple) and len(pts[0]) == 2
            True
        """
        amplitude = float(parameters.get("amplitude", 1.0))
        for _ix, x, measure in self.scan_generator:
            if measure:
                yield x, amplitude * math.sin(x)

    def _about_html(self) -> str:
        """Return an HTML description of the dummy plugin for the *About* tab.

        Returns:
            (str):
                HTML-formatted description string.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = DummyPlugin()
            >>> "<h3>" in plugin._about_html()
            True
        """
        return (
            "<h3>Dummy Plugin</h3>"
            "<p><i>Generates a sine-wave signal for testing. "
            "No hardware is required.</i></p>"
            "<p>Configure the scan generator on the <b>Scan</b> tab to set "
            "the x-values at which measurements are taken. "
            "The y-value at each point is <code>amplitude × sin(x)</code>.</p>"
            "<p>Pass <code>amplitude=&lt;value&gt;</code> in the parameters "
            "dict to scale the output.</p>"
        )
