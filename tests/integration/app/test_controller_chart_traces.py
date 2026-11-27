"""Record controller chart updates in the sequence and Data Manager."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from qtpy.QtWidgets import QMessageBox

from stoner_measurement.instruments.magnet_controller import MagnetState
from stoner_measurement.instruments.pressure_controller import (
    PressureReading,
    PressureStatus,
    PressureUnit,
)
from stoner_measurement.instruments.temperature_controller import SensorStatus
from stoner_measurement.magnet_control.types import MagnetEngineState, MagnetReading
from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
from stoner_measurement.plugins.command.save import SaveCommand
from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.pressure_control.types import PressureEngineReading, PressureEngineState
from stoner_measurement.temperature_control.types import (
    TemperatureChannelReading,
    TemperatureEngineState,
)


def test_panels_publish_chart_updates_for_sequence_and_data_manager(
    managed_measurement_app, monkeypatch
):
    app = managed_measurement_app()
    engine = app._engine
    magnet = app._magnet_panel
    temperature = app._temp_panel
    pressure = app._pressure_panel
    now = datetime.now(UTC)

    magnet._chart_recording.enabled.setChecked(True)
    pressure._chart_recording.name.setText("magnet chart")
    pressure._chart_recording.enabled.setChecked(True)
    assert not pressure._chart_recording.enabled.isChecked()
    assert "already exists" in pressure._chart_recording._message.text()
    pressure._chart_recording.name.setText("Pressure chart")
    for panel in (temperature, pressure):
        panel._chart_recording.enabled.setChecked(True)

    magnet._on_state_updated(
        MagnetEngineState(
            reading=MagnetReading(
                timestamp=now,
                field=0.25,
                current=1.5,
                voltage=0.1,
                heater_on=True,
                state=MagnetState.HOLDING,
                at_target=False,
            ),
            target_field=0.5,
        )
    )
    temperature._on_state_updated(
        TemperatureEngineState(
            readings={"A": TemperatureChannelReading("A", 250.0, now, status=SensorStatus.OK)},
            setpoints={1: 255.0},
            secondary=TemperatureEngineState(
                readings={"A": TemperatureChannelReading("A", 200.0, now, status=SensorStatus.OK)}
            ),
        )
    )
    pressure_state = PressureEngineState(
        reading=PressureEngineReading(now, {}),
        readings={1: PressureReading(1, 1e-5, PressureUnit.MBAR, PressureStatus.OK)},
        flow_actual={1: 0.25},
        flow_unit="sccm",
    )
    pressure._on_state_updated(pressure_state)

    magnet_trace = engine.evaluate_expression(engine.traces_catalog["Magnet chart"])
    assert magnet_trace.df[["Field", "Current", "Target"]].iloc[0].tolist() == [0.25, 1.5, 0.5]
    temp_trace = engine.evaluate_expression(engine.traces_catalog["Temperature chart"])
    assert temp_trace.df[["T_A", "SP_1", "secondary:T_A"]].iloc[0].tolist() == [250, 255, 200]
    trace = engine.evaluate_expression(engine.traces_catalog["Pressure chart"])
    assert trace.x.tolist() == [now.timestamp()]
    assert trace.df["Flow actual 1"].tolist() == [0.25]
    assert trace.units["Pressure 1"] == "mbar"
    pressure._on_duration_changed(1)
    pressure._on_clear_chart()
    assert trace.row_count == 1

    save = SaveCommand()
    save.sequence_engine = engine
    payload = save.build_payload(trace_keys={"Pressure chart"})
    assert {label for label, _ in payload.columns} == {
        "Pressure chart:Unix time (s)",
        "Pressure chart:Pressure 1 (mbar)",
        "Pressure chart:Flow actual 1 (sccm)",
    }

    plot = PlotTraceCommand()
    plot.sequence_engine = engine
    plot.trace_key = "Pressure chart"
    plot.column_key = "Pressure 1"
    plot.execute()
    assert [series.series_id for series in engine.plot_client.series()] == ["Pressure chart"]

    app._act_show_data_manager.trigger()
    manager = app._data_manager
    tabs = manager._tabs
    tabs.setCurrentIndex(
        next(i for i in range(tabs.count()) if tabs.tabText(i) == "Pressure chart")
    )
    page = tabs.currentWidget()
    assert page.model.rowCount() == 1
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    manager._clear_trace_action.trigger()
    assert page.model.rowCount() == 0
    assert page.model.columnCount() == 3
    assert pressure._chart_recording.enabled.isChecked()
    pressure._on_state_updated(pressure_state)
    assert trace.row_count == 1
    engine.evaluate_expression("_chart_traces['Pressure chart'].clear()")
    assert trace.row_count == 0

    pressure._chart_recording.enabled.setChecked(False)
    pressure._on_state_updated(pressure_state)
    assert trace.row_count == 0
    pressure._chart_recording.enabled.setChecked(True)
    pressure._on_state_updated(pressure_state)
    assert trace.row_count == 1
    assert engine.evaluate_expression(engine.traces_catalog["Pressure chart"]) is trace


def test_chart_name_collision_preserves_both_catalogue_entries(engine):
    step = CounterPlugin()
    step.collect_data = True
    name = f"{step.instance_name}.data"
    owner = object()
    chart = engine.register_chart_trace(name, owner)
    engine.append_chart_sample(chart, 123.0, {("temperature", "K"): 200.0})
    engine.append_chart_sample(chart, 124.0, {("temperature", "°C"): -72.0})
    assert chart.df["temperature"].iloc[0] == 200.0
    assert chart.df["temperature"].isna().iloc[1]
    assert chart.units["temperature [2]"] == "°C"

    engine.update_step_plugin_catalog([step])
    assert engine.traces_catalog[name] == name
    chart_key = f"{name} (chart)"
    assert engine.chart_trace(name) is None
    assert engine.evaluate_expression(engine.traces_catalog[chart_key]) is chart
    with pytest.raises(ValueError, match="already exists"):
        engine.register_chart_trace(name.upper(), object())
    assert engine.register_chart_trace(name, owner) is chart

    engine.update_step_plugin_catalog([])
    assert engine.evaluate_expression(engine.traces_catalog[name]) is chart


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
