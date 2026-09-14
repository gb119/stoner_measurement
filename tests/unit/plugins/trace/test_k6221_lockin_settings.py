"""Per-instrument settings, migration and fresh overload checks for 6221 lock-ins."""

import json
from unittest.mock import MagicMock, patch

import pytest
from qtpy.QtWidgets import QCheckBox, QLabel, QTableWidget

from stoner_measurement.instruments.lockin_amplifier import (
    LockInInputCoupling,
    LockInInputSource,
    LockInLineFilter,
)
from stoner_measurement.instruments.srs import SRS830LIAStatus
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace.k6221_multi_sr830 import (
    Keithley6221_MultiSR830Plugin,
    LockInEntry,
    LockInModel,
    LockInReading,
    _lockin_sensitivities,
)


def test_old_common_filters_migrate_with_per_entry_overrides(qapp):
    plugin = Keithley6221_MultiSR830Plugin()
    saved = plugin.to_json()
    saved.update(filter_slope=24, input_coupling="DC", line_filter="BOTH")
    saved["lockins"] = [
        {"label": "old"},
        {"label": "new", "filter_slope": 6, "line_filter": "LINE"},
    ]
    restored = BasePlugin.from_json(saved)
    old, new = restored._lockin_entries
    assert (old.filter_slope, old.input_coupling, old.line_filter) == (
        24,
        LockInInputCoupling.DC,
        LockInLineFilter.BOTH,
    )
    assert (new.filter_slope, new.input_coupling, new.line_filter) == (
        6,
        LockInInputCoupling.DC,
        LockInLineFilter.LINE,
    )
    assert old.input_source is LockInInputSource.A_MINUS_B
    new.input_source = LockInInputSource.A
    current = restored.to_json()
    assert not {"filter_slope", "input_coupling", "line_filter"}.intersection(current)
    round_trip = BasePlugin.from_json(json.loads(json.dumps(current)))
    assert [entry.to_json() for entry in round_trip._lockin_entries] == [
        old.to_json(),
        new.to_json(),
    ]


def test_configuration_applies_independent_input_and_filter_settings(qapp):
    plugin = Keithley6221_MultiSR830Plugin()
    entries = [
        LockInEntry(input_source=LockInInputSource.A, filter_slope=6),
        LockInEntry(
            input_source=LockInInputSource.A_MINUS_B,
            filter_slope=24,
            input_coupling=LockInInputCoupling.DC,
            line_filter=LockInLineFilter.BOTH,
        ),
    ]
    for entry in entries:
        lockin = MagicMock()
        plugin._configure_one_lockin(entry, lockin)
        lockin.set_input_source.assert_called_once_with(entry.input_source)
        lockin.set_filter_slope.assert_called_once_with(entry.filter_slope)
        lockin.set_input_coupling.assert_called_once_with(entry.input_coupling)
        lockin.set_line_filter.assert_called_once_with(entry.line_filter)


def test_controls_edit_only_the_selected_lockin(qapp, managed_qt_widget):
    plugin = Keithley6221_MultiSR830Plugin()
    plugin._lockin_entries.append(LockInEntry(label="second"))
    widget = managed_qt_widget(plugin._plugin_config_tabs())
    table = widget.findChild(QTableWidget)
    rows = {table.verticalHeaderItem(row).text(): row for row in range(table.rowCount())}
    for label, value in (
        ("Filter slope", 24),
        ("Coupling", LockInInputCoupling.DC),
        ("Line filter", LockInLineFilter.BOTH),
        ("Input", LockInInputSource.A),
    ):
        combo = table.cellWidget(rows[label], 1)
        combo.setCurrentIndex(combo.findData(value))
    first, second = plugin._lockin_entries
    assert first.to_json() == LockInEntry().to_json()
    assert (
        second.filter_slope,
        second.input_coupling,
        second.line_filter,
        second.input_source,
    ) == (24, LockInInputCoupling.DC, LockInLineFilter.BOTH, LockInInputSource.A)
    assert "Enable auto-ranging" in [check.text() for check in widget.findChildren(QCheckBox)]
    labels = [label.text() for label in widget.findChildren(QLabel)]
    assert "Auto-ranging low ratio:" in labels
    assert "Auto-ranging high ratio:" in labels
    assert "Filter slope:" not in labels
    assert table.cellWidget(rows["Input"], 0).findData(LockInInputSource.B) == -1


@pytest.mark.parametrize("model", list(LockInModel))
@pytest.mark.parametrize("source", [LockInInputSource.I_1MOHM, LockInInputSource.I_100MOHM])
def test_current_input_ranges_configure_and_auto_range_in_amperes(qapp, model, source):
    plugin = Keithley6221_MultiSR830Plugin()
    values = _lockin_sensitivities(model, source)
    entry = LockInEntry(
        model=model, input_source=source, sensitivity=values[8], auto_sensitivity=False
    )
    plugin._validate_lockin_entry(0, entry)
    lockin = MagicMock()
    plugin._configure_one_lockin(entry, lockin)
    scale = 1e-6 if model is LockInModel.SR830 else 1.0
    assert lockin.set_sensitivity.call_args.args[0] == pytest.approx(values[8] / scale)
    entry.auto_sensitivity = True
    lockin.get_sensitivity.return_value = values[8] / scale
    plugin._configure_one_lockin(entry, lockin)
    assert entry.sensitivity == pytest.approx(values[8])
    plugin._apply_auto_sensitivity_one_lockin(entry, lockin, LockInReading({}, 0.0), values)
    assert entry.sensitivity == values[7]
    assert lockin.set_sensitivity.call_args.args[0] == pytest.approx(values[7] / scale)
    plugin._lockin_entries = [entry]
    plugin._resistance_enabled = True
    assert [(spec.unit, spec.derived_resistance) for spec in plugin._channel_specs()] == [
        ("A", False)
    ]


def test_readback_updates_each_instrument_without_overwriting_its_neighbour(qapp):
    plugin = Keithley6221_MultiSR830Plugin()
    plugin._lockin_entries.append(LockInEntry(label="second"))
    settings = dict(
        time_constant=1.0,
        filter_slope=24,
        input_coupling=LockInInputCoupling.DC,
        line_filter=LockInLineFilter.LINE,
        input_source=LockInInputSource.A,
        sensitivity=1e-3,
        harmonic=1,
        phase=0.0,
        offsets={},
    )
    plugin._apply_read_lockin_settings(1, settings)
    assert plugin._lockin_entries[0].to_json() == LockInEntry().to_json()
    assert plugin._lockin_entries[1].input_source is LockInInputSource.A
    assert plugin._lockin_entries[1].filter_slope == 24


@pytest.mark.parametrize("fresh", [SRS830LIAStatus.NONE, SRS830LIAStatus.FILTER_OVERLOAD])
def test_clear_stale_overload_then_check_reasserted_status(qapp, fresh):
    plugin = Keithley6221_MultiSR830Plugin()
    events = []
    state = {"status": SRS830LIAStatus.INPUT_OR_RESERVE_OVERLOAD}
    lockin = MagicMock()

    def write(command):
        events.append(command)
        state["status"] = SRS830LIAStatus.NONE

    def advance(delay):
        events.append("wait")
        assert delay > 0
        state["status"] = fresh

    def read():
        events.append("read")
        return state["status"]

    lockin.write.side_effect = write
    lockin.read_lia_status.side_effect = read
    plugin._lockins = [lockin]
    with patch(
        "stoner_measurement.plugins.trace.k6221_multi_sr830.time.sleep", side_effect=advance
    ):
        if fresh.has_overload:
            with pytest.raises(RuntimeError, match="overloaded after configuration"):
                plugin._clear_configuration_lia_status()
        else:
            plugin._clear_configuration_lia_status()
    assert events == ["*CLS", "wait", "read"]


def test_7265_status_check_does_not_send_scpi_clear(qapp):
    plugin = Keithley6221_MultiSR830Plugin()
    plugin._lockin_entries[0].model = LockInModel.SR7265
    lockin = MagicMock()
    plugin._lockins = [lockin]
    plugin._clear_configuration_lia_status()
    lockin.write.assert_not_called()
    lockin.check_measurement_status.assert_called_once_with(lockin.read_status.return_value)


@pytest.mark.parametrize("model", list(LockInModel))
def test_current_range_readback_rounding_does_not_disable_auto_ranging(qapp, model):
    plugin = Keithley6221_MultiSR830Plugin()
    entry = LockInEntry(model=model, input_source=LockInInputSource.I_1MOHM, sensitivity=5e-14)
    plugin._validate_lockin_entry(0, entry)
    lockin = MagicMock()
    plugin._apply_auto_sensitivity_one_lockin(
        entry, lockin, LockInReading({}, 0.0), _lockin_sensitivities(model, entry.input_source)
    )
    assert entry.sensitivity == pytest.approx(2e-14, abs=0)
    lockin.set_sensitivity.assert_called_once()


@pytest.mark.parametrize("overrides", [{"filter_slope": 1}, {"input_source": LockInInputSource.B}])
def test_invalid_per_instrument_settings_rejected(qapp, overrides):
    with pytest.raises(ValueError):
        Keithley6221_MultiSR830Plugin._validate_lockin_entry(0, LockInEntry(**overrides))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
