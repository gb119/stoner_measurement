"""Dummy plugin — ships with the package for demonstration and testing.

The :class:`DummyPlugin` computes the DC I-V characteristic of a resistively
shunted Josephson junction (RSJ model).  It requires no hardware and is useful
as a smoke-test and worked example.

This module is part of the :mod:`stoner_measurement.plugins.trace` sub-package.
"""

from __future__ import annotations

import math
from collections.abc import Generator
from typing import Any

import numpy as np

from PyQt6.QtWidgets import QFormLayout, QLineEdit, QWidget

from stoner_measurement.plugins.trace.base import TracePlugin, TraceStatus


class DummyPlugin(TracePlugin):
    """A built-in demo plugin that generates RSJ model I-V data with optional noise.

    Scan points are read from the active
    :attr:`~stoner_measurement.plugins.trace.TracePlugin.scan_generator` and
    interpreted as applied current values *I* (in A).  The corresponding
    voltage is computed using the DC I-V characteristic of the resistively
    shunted Josephson junction (RSJ) model and then perturbed by Gaussian noise:

    * ``V = 0`` when ``|I| < I_c``
    * ``V = sign(I) × R_n × √(I² − I_c²)`` when ``|I| ≥ I_c``
    * ``V += N(0, V_n)`` — independent Gaussian noise added to every sample

    where *I_c* is the critical current, *R_n* is the normal-state resistance,
    and *V_n* is the noise standard deviation.  All three parameters are stored
    as Python expression strings and evaluated via the sequence engine's
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval` method, so
    they can reference any variable or numpy function in the engine namespace
    (e.g. ``"I_start * 2"`` or ``"1e-3 * sqrt(R_n)"``).  They are configurable
    on the *Settings* tab or can be overridden per measurement via the
    ``parameters`` dict passed to :meth:`execute`.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.
    """

    def __init__(self, parent=None) -> None:
        """Initialise the plugin with default RSJ parameters."""
        super().__init__(parent)
        self._critical_current: str = "1.0"
        self._normal_resistance: str = "1.0"
        self._noise_level: str = "0.0"

    @property
    def name(self) -> str:
        """Unique identifier for the dummy plugin."""
        return "Dummy"

    @property
    def trace_title(self) -> str:
        """Human-readable display title for the RSJ I-V trace.

        Returns:
            (str):
                ``"RSJ I-V"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> DummyPlugin().trace_title
            'RSJ I-V'
        """
        return "RSJ I-V"

    @property
    def x_units(self) -> str:
        """Physical units for the applied-current axis.

        Returns:
            (str):
                ``"A"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> DummyPlugin().x_units
            'A'
        """
        return "A"

    @property
    def y_units(self) -> str:
        """Physical units for the voltage axis.

        Returns:
            (str):
                ``"V"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> DummyPlugin().y_units
            'V'
        """
        return "V"

    @property
    def x_label(self) -> str:
        """Axis label for the applied current.

        Returns:
            (str):
                ``"I"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> DummyPlugin().x_label
            'I'
        """
        return "I"

    @property
    def y_label(self) -> str:
        """Axis label for the measured voltage.

        Returns:
            (str):
                ``"V"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> DummyPlugin().y_label
            'V'
        """
        return "V"

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

    def _eval_expr(self, expr: str) -> float:
        """Evaluate *expr* as a float using the sequence engine namespace.

        If the plugin is currently attached to a sequence engine, the
        expression is evaluated using
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval` so that
        numpy functions and all engine variables are available (e.g.
        ``"sqrt(R_n)"`` or ``"1e-3 * I_max"``).  When not attached to an
        engine (e.g. in standalone tests), a plain :func:`float` conversion is
        used as a fallback, which handles simple numeric literals such as
        ``"1.0"`` or ``"1e-3"``.

        Args:
            expr (str):
                Python expression that evaluates to a float.

        Returns:
            (float):
                The evaluated result.
        """
        try:
            return float(self.eval(str(expr)))
        except RuntimeError:
            return float(expr)

    def execute(
        self, parameters: dict[str, Any]
    ) -> Generator[tuple[float, float]]:
        """Yield RSJ I-V data points with optional Gaussian noise.

        Iterates over the scan generator, treating each scan-point value as an
        applied current *I*, and collects ``(I, V)`` for every point whose
        *measure* flag is ``True``.  The noiseless voltage is:

        * ``V = 0`` when ``|I| < I_c``
        * ``V = sign(I) × R_n × √(I² − I_c²)`` when ``|I| ≥ I_c``

        After all points are collected, independent Gaussian noise is added to
        the full voltage array:

        * ``V += np.random.normal(0, V_n, V.size)``

        The noisy ``(I, V)`` pairs are then yielded in scan order.

        All three parameters are evaluated as Python expressions via
        :meth:`_eval_expr`, which delegates to the sequence engine's
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval` method
        when the plugin is attached to an engine.

        Args:
            parameters (dict[str, Any]):
                Step-specific configuration.  Recognised keys:

                * ``"I_c"`` *(str | float)* — critical current expression in A.
                  Defaults to the expression set on the *Settings* tab
                  (initially ``"1.0"``).
                * ``"R_n"`` *(str | float)* — normal-state resistance expression
                  in Ω.  Defaults to the expression set on the *Settings* tab
                  (initially ``"1.0"``).
                * ``"V_n"`` *(str | float)* — noise standard deviation
                  expression in V.  Defaults to the expression set on the
                  *Settings* tab (initially ``"0.0"``).  Set to ``"0.0"`` for
                  noiseless output.

        Yields:
            (tuple[float, float]):
                ``(I, V)`` data point pairs.

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
        i_c = self._eval_expr(str(parameters.get("I_c", self._critical_current)))
        r_n = self._eval_expr(str(parameters.get("R_n", self._normal_resistance)))
        v_n_expr = str(parameters.get("V_n", self._noise_level))

        currents: list[float] = []
        voltages: list[float] = []
        for _ix, current, measure in self.scan_generator:
            if measure:
                abs_i = abs(current)
                if abs_i < i_c:
                    voltage = 0.0
                else:
                    voltage = math.copysign(
                        r_n * math.sqrt(max(0.0, abs_i**2 - i_c**2)), current
                    )
                currents.append(current)
                voltages.append(voltage)

        v_arr = np.array(voltages)
        v_n = self._eval_expr(v_n_expr)
        if v_n > 0.0:
            v_arr = v_arr + np.random.normal(0, v_n, v_arr.size)

        yield from zip(currents, v_arr.tolist())

    def _plugin_config_tabs(self) -> QWidget:
        """Return a settings widget with expression-string controls for *I_c*, *R_n*, and *V_n*.

        Creates a :class:`~PyQt6.QtWidgets.QFormLayout` with three
        :class:`~PyQt6.QtWidgets.QLineEdit` widgets, each accepting a Python
        expression string that will be evaluated via the sequence engine
        namespace at measurement time:

        * **I_c** — critical current in A (default ``"1.0"``).
        * **R_n** — normal-state resistance in Ω (default ``"1.0"``).
        * **V_n** — noise standard deviation in V (default ``"0.0"``).

        Returns:
            (QWidget):
                Configured settings widget for the *Settings* tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from PyQt6.QtWidgets import QWidget
            >>> isinstance(DummyPlugin()._plugin_config_tabs(), QWidget)
            True
        """
        widget = QWidget()
        layout = QFormLayout(widget)

        tooltip = (
            "Python expression evaluated in the sequence engine namespace. "
            "Simple numeric literals (e.g. '1.0', '1e-3') and numpy functions "
            "are supported."
        )

        i_c_edit = QLineEdit(self._critical_current)
        i_c_edit.setToolTip(tooltip)

        r_n_edit = QLineEdit(self._normal_resistance)
        r_n_edit.setToolTip(tooltip)

        v_n_edit = QLineEdit(self._noise_level)
        v_n_edit.setToolTip(tooltip + " Use '0.0' for noiseless output.")

        def _update_i_c() -> None:
            self._critical_current = i_c_edit.text().strip()

        def _update_r_n() -> None:
            self._normal_resistance = r_n_edit.text().strip()

        def _update_v_n() -> None:
            self._noise_level = v_n_edit.text().strip()

        i_c_edit.editingFinished.connect(_update_i_c)
        r_n_edit.editingFinished.connect(_update_r_n)
        v_n_edit.editingFinished.connect(_update_v_n)

        layout.addRow("Critical current I_c (A):", i_c_edit)
        layout.addRow("Normal resistance R_n (\u03a9):", r_n_edit)
        layout.addRow("Noise level V_n (V):", v_n_edit)
        return widget

    def _about_html(self) -> str:
        """Return an HTML description of the RSJ model for the *About* tab.

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
            "<h3>Dummy Plugin \u2013 RSJ Model</h3>"
            "<p><i>Simulates the DC I-V characteristic of a resistively "
            "shunted Josephson junction with optional Gaussian noise. "
            "No hardware is required.</i></p>"
            "<p>Configure the scan generator on the <b>Scan</b> tab to set "
            "the applied current values at which voltages are computed.</p>"
            "<p>The voltage at each current point <i>I</i> is:</p>"
            "<ul>"
            "<li><code>V = 0</code> when "
            "<code>|I| &lt; I<sub>c</sub></code></li>"
            "<li><code>V = sign(I) &times; R<sub>n</sub> &times; "
            "&radic;(I&sup2; &minus; I<sub>c</sub>&sup2;)</code> "
            "when <code>|I| &ge; I<sub>c</sub></code></li>"
            "<li><code>V += N(0, V<sub>n</sub>)</code> &mdash; "
            "independent Gaussian noise added to every sample</li>"
            "</ul>"
            "<p>Set <code>I<sub>c</sub></code> (critical current), "
            "<code>R<sub>n</sub></code> (normal-state resistance), and "
            "<code>V<sub>n</sub></code> (noise standard deviation, as a "
            "Python expression) on the <b>Settings</b> tab. "
            "Use <code>V<sub>n</sub> = 0.0</code> for noiseless output.</p>"
        )
