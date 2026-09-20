"""X-ray-diffractometer-backed state-scan plugin."""

from __future__ import annotations

import math

from qtpy.QtWidgets import QFormLayout, QWidget

from stoner_measurement.plugins.state._xray_diffractometer_plugin import (
    XrayDiffractometerPluginMixin,
)
from stoner_measurement.plugins.state_scan.base import StateScanPlugin
from stoner_measurement.scan import SteppedScanGenerator
from stoner_measurement.ui.widgets import SISpinBox


class XrayDiffractometerScanPlugin(XrayDiffractometerPluginMixin, StateScanPlugin):
    """Scan an X-ray diffractometer angle through discrete set-points.

    Use this state scan to run nested measurement steps at a sequence of
    diffractometer angles. The standard **Scan** and **Data** tabs configure the
    point generator and collected outputs. New instances default to the
    multi-stage stepped generator. The **Settings** tab selects
    **Theta/omega scan**, **Theta-2theta**, or **Detector/2theta scan**.
    Motion uses the speed, datum offset, and mechanics configured in the shared
    X-ray engine. The preferred instrument is reconnected automatically when
    necessary and remains connected after the scan. At each point whose
    measurement flag is true, the plugin moves to the target and then acquires
    detector counts. The expression-capable count time is evaluated separately
    at each angle; the engine's prior count time is restored after the scan.

    In **Theta-2theta** mode, scan-generator values and ``value`` are detector
    ``2-theta`` angles; the corresponding theta target is calculated
    internally. The instance exposes ``value``, ``ix``, ``theta``,
    ``two_theta``, and ``counts`` in the sequence namespace.

    Attributes:
        axes (XrayMotionMode):
            Motion relationship selected on Settings.
        count_time (float | str):
            Integration time in seconds or per-point expression.
        theta (float):
            Latest theta/omega angle in degrees.
        two_theta (float):
            Latest detector angle in degrees.
        counts (float):
            Latest detector count.
        instance_name (str):
            Inherited Python identifier for this instance in the Script tab and
            QtConsole.
        comment (str):
            Inherited optional note displayed beside this step.
        sequence_engine (SequenceEngine | None):
            Inherited owning engine and its live namespace; None while
            detached.
        scan_generator (BaseScanGenerator):
            Inherited generator defining successive sequence points.
        value (float):
            Inherited current sequence control value.
        ix (int):
            Inherited zero-based iteration index.
        meas_flag (bool):
            Inherited flag indicating a measurement point.
        collect_data (bool):
            Inherited switch enabling collection of selected sequence outputs.
        data (TraceData):
            Inherited accumulated table; inspect data.df after collection.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        With a sequence instance named ``xray_diffractometer_scan``, use
        the QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            from stoner_measurement.xray_control import XrayMotionMode
            xray_diffractometer_scan.axes = XrayMotionMode.COUPLED
            xray_diffractometer_scan.count_time = 1.0
            xray_diffractometer_scan.data.df.head()
    """

    _scan_generator_class = SteppedScanGenerator

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._init_xray_diffractometer_plugin()
        self.count_time: float | str = 1.0
        self._original_count_duration_s: float | None = None

    @property
    def name(self) -> str:
        return "X-ray Diffractometer Scan"

    @property
    def state_name(self) -> str:
        return "Diffractometer Angle"

    @property
    def units(self) -> str:
        return "deg"

    def configure(self) -> None:
        """Remember the panel count time so the scan can restore it."""
        engine = self._ensure_connected()
        self._original_count_duration_s = engine.count_duration_s

    def disconnect(self) -> None:
        """Restore the count time that was configured before the scan."""
        if self._original_count_duration_s is None:
            return
        try:
            self._engine().set_count_duration(self._original_count_duration_s)
        finally:
            self._original_count_duration_s = None

    def ramp_to(self, value: float, poll_interval: float = 0.5) -> None:
        """Move first, then acquire counts for measurement-enabled points."""
        lo, hi = self.limits
        in_range = not (
            (math.isfinite(lo) and value < lo)
            or (math.isfinite(hi) and value > hi)
        )
        super().ramp_to(value, poll_interval=poll_interval)
        if not in_range or not self.meas_flag or not self.is_at_target():
            return
        duration_s = self.eval_float(self.count_time)
        self._engine().set_count_duration(duration_s)
        self._engine().count()

    def to_json(self) -> dict[str, object]:
        data = super().to_json()
        data.update(self._xray_settings_to_json())
        data["count_time"] = self.count_time
        return data

    def _restore_from_json(self, data: dict[str, object]) -> None:
        super()._restore_from_json(data)
        self._restore_xray_settings(data)
        self.count_time = data.get("count_time", 1.0)

    def _add_xray_settings_rows(
        self, layout: QFormLayout, parent: QWidget
    ) -> None:
        count_time = SISpinBox(
            suffix="s",
            value=self.count_time,
            allow_expressions=True,
            parent=parent,
        )
        count_time.setObjectName("xray_count_time")
        count_time.setToolTip(
            "Evaluated at every measurement point; for example "
            "0.5 + abs(xray_scan.value) / 20"
        )
        count_time.setMinimum(0.001)
        count_time.setMaximum(86_400.0)
        count_time.valueChanged.connect(
            lambda value: setattr(self, "count_time", value)
        )
        layout.addRow("Count time:", count_time)
