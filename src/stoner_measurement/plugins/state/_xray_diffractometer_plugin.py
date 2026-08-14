"""Shared engine-backed behaviour for X-ray diffractometer state plugins."""

from __future__ import annotations

from qtpy.QtWidgets import QComboBox, QFormLayout, QVBoxLayout, QWidget

from stoner_measurement.xray_control import (
    XrayControllerEngine,
    XrayMotionMode,
)

XRAY_MOTION_OPTIONS = (
    ("Theta/omega scan", XrayMotionMode.THETA),
    ("Theta-2theta", XrayMotionMode.COUPLED),
    ("Detector/2theta scan", XrayMotionMode.TWO_THETA),
)


def normalise_xray_motion_mode(value: object) -> XrayMotionMode:
    """Return a valid persisted X-ray motion mode."""
    if isinstance(value, XrayMotionMode):
        return value
    try:
        return XrayMotionMode(str(value))
    except ValueError:
        return XrayMotionMode.COUPLED


def add_xray_motion_mode_row(
    layout: QFormLayout,
    owner: object,
    parent: QWidget,
) -> QComboBox:
    """Add the common axis-selection row and bind it to ``owner.axes``."""
    combo = QComboBox(parent)
    combo.setObjectName("xray_motion_axes")
    for label, mode in XRAY_MOTION_OPTIONS:
        combo.addItem(label, mode)
    combo.setCurrentIndex(combo.findData(owner.axes))
    combo.currentIndexChanged.connect(
        lambda index: setattr(owner, "axes", combo.itemData(index))
    )
    layout.addRow("Axes:", combo)
    return combo


class XrayDiffractometerPluginMixin:
    """Shared lifecycle and motion API for X-ray state-scan plugins."""

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"xray"})

    def _init_xray_diffractometer_plugin(self) -> None:
        self.axes = XrayMotionMode.COUPLED

    def _engine(self) -> XrayControllerEngine:
        return XrayControllerEngine.instance()

    def _ensure_connected(self) -> XrayControllerEngine:
        engine = self._engine()
        if engine.connected_driver is None:
            engine.connect_preferred_driver()
        if engine.connected_driver is None:
            raise RuntimeError("No X-ray diffractometer is connected.")
        return engine

    def connect(self) -> None:
        """Connect the preferred diffractometer if necessary."""
        self._ensure_connected()

    def configure(self) -> None:
        """Retain the speed and mechanics configured on the shared engine."""

    def disconnect(self) -> None:
        """Leave the shared diffractometer engine connected."""

    @property
    def limits(self) -> tuple[float, float]:
        """Return limits for the coordinate controlled by the selected axes."""
        engine = self._engine()
        mechanics = engine.mechanics
        if self.axes is XrayMotionMode.TWO_THETA:
            return (mechanics.two_theta.minimum_deg, mechanics.two_theta.maximum_deg)
        if self.axes is XrayMotionMode.THETA:
            return (mechanics.theta.minimum_deg, mechanics.theta.maximum_deg)
        offset = engine.get_engine_state().two_theta_offset_deg
        return (
            max(mechanics.theta.minimum_deg, (mechanics.two_theta.minimum_deg - offset) / 2.0),
            min(mechanics.theta.maximum_deg, (mechanics.two_theta.maximum_deg - offset) / 2.0),
        )

    def set_state(self, value: float) -> None:
        """Move the selected axes using the speed configured in the engine."""
        self._ensure_connected().move_to(float(value), self.axes)

    def get_state(self) -> float:
        """Return the measured coordinate corresponding to the selected axes."""
        engine = self._ensure_connected()
        state = engine.get_engine_state()
        if state.snapshot is None:
            state = engine.read_controller_state() or state
        if state.snapshot is None:
            raise RuntimeError("The X-ray diffractometer has no position reading.")
        if self.axes is XrayMotionMode.TWO_THETA:
            return float(state.snapshot.two_theta_deg)
        return float(state.snapshot.theta_deg)

    def is_at_target(self) -> bool:
        """Refresh the engine state and report whether motion has completed."""
        engine = self._ensure_connected()
        state = engine.read_controller_state() or engine.get_engine_state()
        return bool(state.at_target and not state.moving)

    @property
    def theta(self) -> float:
        """Return the latest measured theta coordinate."""
        snapshot = self._engine().get_engine_state().snapshot
        return float("nan") if snapshot is None else float(snapshot.theta_deg)

    @property
    def two_theta(self) -> float:
        """Return the latest measured 2-theta coordinate."""
        snapshot = self._engine().get_engine_state().snapshot
        return float("nan") if snapshot is None else float(snapshot.two_theta_deg)

    @property
    def counts(self) -> float:
        """Return the detector counts from the latest snapshot."""
        snapshot = self._engine().get_engine_state().snapshot
        return float("nan") if snapshot is None else float(snapshot.counts)

    def reported_values(self) -> dict[str, str]:
        """Add measured positions and counts to the standard scan outputs."""
        values = super().reported_values()
        var = self.instance_name
        values.update(
            {
                f"{var}:Theta": f"{var}.theta",
                f"{var}:2-Theta": f"{var}.two_theta",
                f"{var}:Counts": f"{var}.counts",
            }
        )
        return values

    def _xray_settings_to_json(self) -> dict[str, object]:
        return {"axes": self.axes.value}

    def _restore_xray_settings(self, data: dict[str, object]) -> None:
        self.axes = normalise_xray_motion_mode(
            data.get("axes", XrayMotionMode.COUPLED.value)
        )

    def _plugin_config_tabs(self) -> QWidget:
        widget = QWidget()
        root = QVBoxLayout(widget)
        form = QFormLayout()
        add_xray_motion_mode_row(form, self, widget)
        self._add_xray_settings_rows(form, widget)
        root.addLayout(form)
        root.addStretch(1)
        return widget

    def _add_xray_settings_rows(self, layout: QFormLayout, parent: QWidget) -> None:
        """Add subclass-specific rows to the X-ray settings form."""
