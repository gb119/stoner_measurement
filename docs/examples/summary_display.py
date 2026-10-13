"""Example external display: inspect sample counts without a graphics library.

Copy this module into your own package and register SummaryDisplayFactory.
It intentionally offers a diagnostic summary rather than a production chart.
"""

from dataclasses import replace

import numpy as np
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget

from stoner_measurement.core.plotting.contracts import (
    ClearPlot,
    ConfigureAxes,
    CoordinateSystem,
    PlotCapabilities,
    PlotData,
    PlotOperation,
    PlotRequest,
    Presentation,
    SeriesDescription,
    SeriesUpdate,
    UpdateMode,
)
from stoner_measurement.core.plotting.service import UnsupportedDisplayOperation
from stoner_measurement.core.plotting.state import DisplayState, SeriesState
from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.ui.plotting.interfaces import DISPLAY_CONTRACT_VERSION


class SummaryDisplayFactory:
    """Metadata construction creates no widgets or instrument connections."""

    factory_id = "summary"
    name = "Sample summary (example)"
    contract_version = DISPLAY_CONTRACT_VERSION
    capabilities = PlotCapabilities(
        layouts=frozenset({(CoordinateSystem.CARTESIAN, 2)}),
        presentations=frozenset({Presentation.LINE, Presentation.POINTS}),
        operations=frozenset(
            {PlotOperation.UPDATE_SERIES, PlotOperation.CONFIGURE_AXES, PlotOperation.CLEAR}
        ),
        named_axes=True,
    )

    def create(self, parent):
        """The host calls this on the GUI thread, only when selected."""
        return SummaryDisplay(parent)


class SummaryDisplay(QWidget):
    """An adapter may also be its own parent-owned widget."""

    changed = pyqtSignal()
    capabilities = SummaryDisplayFactory.capabilities
    supported_styles = frozenset()

    def __init__(self, parent):
        super().__init__(parent)
        self.widget = self
        self._state = DisplayState()
        self._heading = "Samples"
        self._closed = False
        self.label = QLabel(self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addStretch()
        self._refresh()

    def validate(self, payload):
        """Reject before mutation; capability checks alone are insufficient."""
        reasons = self.capabilities.unsupported_reasons(PlotRequest(payload))
        if reasons:
            raise UnsupportedDisplayOperation(" ".join(reasons))
        if isinstance(payload, SeriesUpdate):
            if payload.style:
                raise UnsupportedDisplayOperation("Summary does not render plot styles.")
            old = next(
                (
                    entry.update
                    for entry in self._state.series
                    if entry.update.series_id == payload.series_id
                ),
                None,
            )
            if old is not None and payload.mode == UpdateMode.APPEND:
                if (
                    old.binding != payload.binding
                    or old.coordinates != payload.coordinates
                    or set(old.data.channels) != set(payload.data.channels)
                    or old.data.metadata != payload.data.metadata
                    or set(old.data.uncertainties) != set(payload.data.uncertainties)
                ):
                    raise ValueError("Append requires matching channels, bindings and metadata.")

    def apply(self, payload):
        """Apply completely before emitting descriptions and returning."""
        self.validate(payload)
        if isinstance(payload, SeriesUpdate):
            entries = {entry.update.series_id: entry for entry in self._state.series}
            previous = entries.get(payload.series_id)
            if previous is not None and payload.mode == UpdateMode.APPEND:
                old = previous.update.data
                data = PlotData(
                    {
                        key: np.concatenate((old.channels[key], values))
                        for key, values in payload.data.channels.items()
                    },
                    metadata=payload.data.metadata,
                    uncertainties={
                        key: np.concatenate((old.uncertainties[key], values))
                        for key, values in payload.data.uncertainties.items()
                    },
                )
                payload = replace(payload, data=data, mode=UpdateMode.REPLACE)
            entries[payload.series_id] = SeriesState(
                payload, previous.visible if previous is not None else True
            )
            self._state = replace(self._state, series=tuple(entries.values()))
        elif isinstance(payload, ConfigureAxes):
            axes = {axis.name: axis for axis in self._state.axes}
            axes.update({axis.name: axis for axis in payload.axes})
            self._state = replace(self._state, axes=tuple(axes.values()))
        elif isinstance(payload, ClearPlot):
            self._state = replace(self._state, series=(), markers=())
        self._refresh()
        self.changed.emit()

    def _refresh(self):
        rows = [self._heading]
        rows.extend(
            f"{entry.update.title or entry.update.series_id}: "
            f"{len(entry.update.data.channels[entry.update.binding.x])} samples"
            for entry in self._state.series
            if entry.visible
        )
        self.label.setText("\n".join(rows))

    def descriptions(self):
        return self._state.axes, tuple(
            SeriesDescription(
                entry.update.series_id,
                entry.update.title or entry.update.series_id,
                entry.update.binding,
                entry.update.coordinates,
                entry.visible,
            )
            for entry in self._state.series
        )

    def export_state(self):
        return replace(self._state, renderer_settings=self.export_settings())

    def import_state(self, state):
        if not isinstance(state, DisplayState):
            raise TypeError("Expected DisplayState.")
        if state.markers:
            raise UnsupportedDisplayOperation("Summary does not render markers.")
        # Validate against an empty candidate, not data left by a previous import.
        for entry in state.series:
            self.validate(replace(entry.update, mode=UpdateMode.REPLACE))
        self.validate(ConfigureAxes(state.axes))
        self.import_settings(state.renderer_settings)
        self._state = state
        self._refresh()
        self.changed.emit()

    def export_settings(self):
        return {"version": 1, "heading": self._heading}

    def import_settings(self, settings):
        if settings and (
            settings.get("version") != 1 or not isinstance(settings.get("heading"), str)
        ):
            raise ValueError("Unsupported summary preferences.")
        self._heading = settings.get("heading", "Samples")
        self._refresh()

    def close(self):
        if not self._closed:
            self._closed = True
            super().close()
