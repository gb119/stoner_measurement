"""Tests for NI-DAQmx discovery and task-definition selection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from qtpy.QtCore import Qt

from stoner_measurement.ui.widgets import SIComboBox, SISpinBox
from stoner_measurement.ui.widgets.daqmx_task_widget import (
    DaqmxChannelFamily,
    DaqmxDeviceInfo,
    DaqmxDiscoveryError,
    DaqmxInputRange,
    DaqmxNamedResource,
    DaqmxSelectionMode,
    DaqmxSystemInfo,
    DaqmxTaskDefinition,
    DaqmxTaskDefinitionWidget,
    DaqmxTaskKind,
    DaqmxTerminalConfiguration,
    _discover_from_system,
)


class _NamedCollection:
    def __init__(self, names, *, name_attribute="channel_names", values=None):
        setattr(self, name_attribute, list(names))
        self._values = values or {name: name for name in names}

    def __getitem__(self, name):
        return self._values[name]


class _FakeLoadedTask:
    def __init__(self, channel_type):
        self.channels = SimpleNamespace(chan_type=SimpleNamespace(name=channel_type))
        self.closed = False

    def close(self):
        self.closed = True


class _FakePersistedTask:
    def __init__(self, loaded_task):
        self.loaded_task = loaded_task

    def load(self):
        return self.loaded_task


class _FakeTemporaryTask:
    def __init__(self):
        self.channels = SimpleNamespace(chan_type=None)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def add_global_channels(self, channels):
        self.channels.chan_type = SimpleNamespace(name=channels[0].channel_type)


def _fake_system():
    device = SimpleNamespace(
        product_type="PCIe-6363",
        ai_voltage_rngs=[-10.0, 10.0, -5.0, 5.0, -1.0, 1.0, -0.2, 0.2],
        ai_physical_chans=_NamedCollection(["Dev1/ai0", "Dev1/ai1"]),
        ao_physical_chans=_NamedCollection(["Dev1/ao0"]),
        di_lines=_NamedCollection(["Dev1/port0/line0"]),
        di_ports=_NamedCollection(["Dev1/port0"]),
        do_lines=_NamedCollection(["Dev1/port0/line1"]),
        do_ports=_NamedCollection(["Dev1/port0"]),
        ci_physical_chans=_NamedCollection(["Dev1/ctr0"]),
        co_physical_chans=_NamedCollection(["Dev1/ctr1"]),
        terminals=["/Dev1/PFI0", "/Dev1/ai/SampleClock"],
    )
    global_values = {
        "Temperature": SimpleNamespace(channel_type="ANALOG_INPUT"),
        "Heater": SimpleNamespace(channel_type="ANALOG_OUTPUT"),
    }
    acquisition_task = _FakeLoadedTask("ANALOG_INPUT")
    output_task = _FakeLoadedTask("ANALOG_OUTPUT")
    system = SimpleNamespace(
        devices=_NamedCollection(["Dev1"], name_attribute="device_names", values={"Dev1": device}),
        scales=_NamedCollection(["Kelvin", "Pressure"], name_attribute="scale_names"),
        global_channels=_NamedCollection(
            ["Temperature", "Heater"],
            name_attribute="global_channel_names",
            values=global_values,
        ),
        tasks=_NamedCollection(
            ["Acquire slow", "Generate waveform"],
            name_attribute="task_names",
            values={
                "Acquire slow": _FakePersistedTask(acquisition_task),
                "Generate waveform": _FakePersistedTask(output_task),
            },
        ),
    )
    return system, acquisition_task, output_task


def _snapshot() -> DaqmxSystemInfo:
    return DaqmxSystemInfo(
        devices=(
            DaqmxDeviceInfo(
                name="Dev1",
                product_type="PCIe-6363",
                analog_inputs=("Dev1/ai0", "Dev1/ai1"),
                analog_input_ranges=(0.2, 1.0, 5.0, 10.0),
                analog_outputs=("Dev1/ao0",),
                digital_inputs=("Dev1/port0/line0",),
                digital_outputs=("Dev1/port0/line1",),
            ),
        ),
        scales=("Kelvin", "Pressure"),
        global_channels=(
            DaqmxNamedResource(
                "Temperature", DaqmxTaskKind.ACQUISITION, DaqmxChannelFamily.ANALOG
            ),
            DaqmxNamedResource(
                "Gate", DaqmxTaskKind.ACQUISITION, DaqmxChannelFamily.DIGITAL
            ),
            DaqmxNamedResource(
                "Heater", DaqmxTaskKind.OUTPUT, DaqmxChannelFamily.ANALOG
            ),
        ),
        saved_tasks=(
            DaqmxNamedResource(
                "Acquire slow", DaqmxTaskKind.ACQUISITION, DaqmxChannelFamily.ANALOG
            ),
            DaqmxNamedResource(
                "Watch gate", DaqmxTaskKind.ACQUISITION, DaqmxChannelFamily.DIGITAL
            ),
            DaqmxNamedResource(
                "Generate waveform", DaqmxTaskKind.OUTPUT, DaqmxChannelFamily.ANALOG
            ),
        ),
    )


def _tree_channel_names(widget: DaqmxTaskDefinitionWidget) -> list[str]:
    names = []
    for group_index in range(widget.physical_tree.topLevelItemCount()):
        group = widget.physical_tree.topLevelItem(group_index)
        for child_index in range(group.childCount()):
            child = group.child(child_index)
            names.append(child.data(0, Qt.ItemDataRole.UserRole))
    return names


def _list_names(widget: DaqmxTaskDefinitionWidget) -> list[str]:
    return [
        widget.global_channel_list.item(index).text()
        for index in range(widget.global_channel_list.count())
    ]


def test_discovery_uses_official_system_collections_and_closes_loaded_tasks():
    system, acquisition_task, output_task = _fake_system()

    result = _discover_from_system(system, _FakeTemporaryTask)

    assert result.devices[0].analog_inputs == ("Dev1/ai0", "Dev1/ai1")
    assert result.devices[0].analog_input_ranges == (0.2, 1.0, 5.0, 10.0)
    assert result.devices[0].digital_outputs == ("Dev1/port0", "Dev1/port0/line1")
    assert result.devices[0].terminals == ("/Dev1/PFI0", "/Dev1/ai/SampleClock")
    assert result.scales == ("Kelvin", "Pressure")
    assert result.global_channels == (
        DaqmxNamedResource("Heater", DaqmxTaskKind.OUTPUT, DaqmxChannelFamily.ANALOG),
        DaqmxNamedResource(
            "Temperature", DaqmxTaskKind.ACQUISITION, DaqmxChannelFamily.ANALOG
        ),
    )
    assert result.saved_tasks == (
        DaqmxNamedResource(
            "Acquire slow", DaqmxTaskKind.ACQUISITION, DaqmxChannelFamily.ANALOG
        ),
        DaqmxNamedResource(
            "Generate waveform", DaqmxTaskKind.OUTPUT, DaqmxChannelFamily.ANALOG
        ),
    )
    assert acquisition_task.closed
    assert output_task.closed


def test_widget_defers_discovery_and_lists_acquisition_resources(managed_qt_widget):
    calls = []
    widget = managed_qt_widget(
        DaqmxTaskDefinitionWidget(discovery_provider=lambda: calls.append(True) or _snapshot())
    )

    assert calls == []
    assert not hasattr(widget, "task_kind_combo")
    widget.refresh()

    assert calls == [True]
    assert widget.device_combo.currentData() == "Dev1"
    assert _tree_channel_names(widget) == ["Dev1/ai0", "Dev1/ai1", "Dev1/port0/line0"]
    assert _list_names(widget) == ["Gate", "Temperature"]
    assert [
        widget.saved_task_combo.itemData(index) for index in range(widget.saved_task_combo.count())
    ] == [
        "",
        "Acquire slow",
        "Watch gate",
    ]


def test_output_direction_filters_channels_global_channels_and_tasks(managed_qt_widget):
    widget = managed_qt_widget(DaqmxTaskDefinitionWidget(task_kind=DaqmxTaskKind.OUTPUT))
    widget.set_snapshot(_snapshot())
    widget.set_definition(
        DaqmxTaskDefinition(
            task_kind=DaqmxTaskKind.OUTPUT,
            physical_channels=("Dev1/ao0",),
            global_channels=("Heater",),
            saved_task="Generate waveform",
        )
    )

    assert _tree_channel_names(widget) == ["Dev1/ao0", "Dev1/port0/line1"]
    assert _list_names(widget) == ["Heater"]
    assert [
        widget.saved_task_combo.itemData(index) for index in range(widget.saved_task_combo.count())
    ] == [
        "",
        "Generate waveform",
    ]


@pytest.mark.parametrize(
    ("family", "physical_channels", "global_channels", "saved_tasks"),
    [
        (
            DaqmxChannelFamily.ANALOG,
            ["Dev1/ai0", "Dev1/ai1"],
            ["Temperature"],
            ["", "Acquire slow"],
        ),
        (
            DaqmxChannelFamily.DIGITAL,
            ["Dev1/port0/line0"],
            ["Gate"],
            ["", "Watch gate"],
        ),
    ],
)
def test_acquisition_channel_family_filters_all_resource_sources(
    managed_qt_widget, family, physical_channels, global_channels, saved_tasks
):
    widget = managed_qt_widget(DaqmxTaskDefinitionWidget(channel_family=family))

    widget.set_snapshot(_snapshot())

    assert widget.channel_family() is family
    assert _tree_channel_names(widget) == physical_channels
    assert _list_names(widget) == global_channels
    assert [
        widget.saved_task_combo.itemData(index)
        for index in range(widget.saved_task_combo.count())
    ] == saved_tasks


def test_channel_lists_use_direction_specific_fixed_heights(managed_qt_widget):
    acquisition = managed_qt_widget(DaqmxTaskDefinitionWidget())
    output = managed_qt_widget(
        DaqmxTaskDefinitionWidget(task_kind=DaqmxTaskKind.OUTPUT)
    )

    assert acquisition._visible_channel_rows == 4
    assert output._visible_channel_rows == 1
    assert acquisition.minimumHeight() == acquisition.maximumHeight()
    assert output.minimumHeight() == output.maximumHeight()
    assert acquisition.physical_tree.height() > output.physical_tree.height()
    assert acquisition.global_channel_list.height() > output.global_channel_list.height()


def test_definition_with_wrong_direction_is_rejected(managed_qt_widget):
    widget = managed_qt_widget(DaqmxTaskDefinitionWidget(task_kind=DaqmxTaskKind.OUTPUT))

    with pytest.raises(ValueError, match="acquisition definition"):
        widget.set_definition(DaqmxTaskDefinition(task_kind=DaqmxTaskKind.ACQUISITION))


def test_definition_round_trip_covers_all_three_source_modes(managed_qt_widget):
    widget = managed_qt_widget(DaqmxTaskDefinitionWidget())
    widget.set_snapshot(_snapshot())
    definition = DaqmxTaskDefinition(
        task_kind=DaqmxTaskKind.ACQUISITION,
        selection_mode=DaqmxSelectionMode.GLOBAL_CHANNELS,
        device="Dev1",
        physical_channels=("Dev1/ai1",),
        custom_scale="Kelvin",
        terminal_configuration=DaqmxTerminalConfiguration.NRSE,
        global_channels=("Temperature",),
        saved_task="Acquire slow",
    )

    widget.set_definition(definition)

    assert widget.definition() == definition
    assert DaqmxTaskDefinition.from_dict(definition.to_dict()) == definition
    legacy_data = definition.to_dict()
    legacy_data.pop("terminal_configuration")
    assert (
        DaqmxTaskDefinition.from_dict(legacy_data).terminal_configuration
        is DaqmxTerminalConfiguration.DEFAULT
    )


def test_analogue_acquisition_uses_one_terminal_mode_for_all_channels(managed_qt_widget):
    widget = managed_qt_widget(
        DaqmxTaskDefinitionWidget(channel_family=DaqmxChannelFamily.ANALOG)
    )
    widget.set_snapshot(_snapshot())
    definition = DaqmxTaskDefinition(
        device="Dev1",
        physical_channels=("Dev1/ai0", "Dev1/ai1"),
        terminal_configuration=DaqmxTerminalConfiguration.DIFFERENTIAL,
        input_ranges=(
            DaqmxInputRange("Dev1/ai0", 0.2),
            DaqmxInputRange("Dev1/ai1", 5.0),
        ),
    )

    widget.set_definition(definition)

    assert widget.definition() == definition
    assert DaqmxTaskDefinition.from_dict(definition.to_dict()) == definition
    assert not widget.terminal_configuration_combo.isHidden()
    assert all(isinstance(selector, SIComboBox) for selector in widget._range_widgets.values())


def test_new_analogue_channels_default_to_plus_or_minus_ten_volts(managed_qt_widget):
    widget = managed_qt_widget(
        DaqmxTaskDefinitionWidget(channel_family=DaqmxChannelFamily.ANALOG)
    )
    widget.set_snapshot(_snapshot())

    widget.set_definition(
        DaqmxTaskDefinition(device="Dev1", physical_channels=("Dev1/ai0",))
    )

    assert widget.definition().input_ranges == (DaqmxInputRange("Dev1/ai0"),)


def test_analogue_range_uses_si_spinbox_when_device_ranges_are_unavailable(
    managed_qt_widget,
):
    widget = managed_qt_widget(
        DaqmxTaskDefinitionWidget(channel_family=DaqmxChannelFamily.ANALOG)
    )
    widget.set_snapshot(
        DaqmxSystemInfo(devices=(DaqmxDeviceInfo("Dev1", analog_inputs=("Dev1/ai0",)),))
    )

    assert isinstance(widget._range_widgets["Dev1/ai0"], SISpinBox)


def test_legacy_minimum_and_maximum_are_migrated_to_a_symmetric_range():
    restored = DaqmxInputRange.from_dict(
        {"channel": "Dev1/ai0", "minimum": -2.0, "maximum": 5.0}
    )

    assert restored == DaqmxInputRange("Dev1/ai0", 5.0)


def test_digital_selector_hides_analogue_only_settings(managed_qt_widget):
    widget = managed_qt_widget(
        DaqmxTaskDefinitionWidget(channel_family=DaqmxChannelFamily.DIGITAL)
    )

    assert widget.terminal_configuration_combo.isHidden()
    assert widget.scale_combo.isHidden()


def test_refresh_preserves_configured_values_missing_from_new_snapshot(managed_qt_widget):
    widget = managed_qt_widget(DaqmxTaskDefinitionWidget(discovery_provider=DaqmxSystemInfo))
    widget.set_snapshot(_snapshot())
    definition = DaqmxTaskDefinition(
        selection_mode=DaqmxSelectionMode.PHYSICAL_CHANNELS,
        device="Dev1",
        physical_channels=("Dev1/ai0",),
        custom_scale="Kelvin",
    )
    widget.set_definition(definition)

    widget.refresh()

    assert widget.definition().physical_channels == ("Dev1/ai0",)
    assert widget.definition().custom_scale == "Kelvin"


def test_discovery_failure_is_reported_without_destroying_selection(managed_qt_widget):
    def fail():
        raise DaqmxDiscoveryError("NI-DAQmx is unavailable")

    widget = managed_qt_widget(DaqmxTaskDefinitionWidget(discovery_provider=fail))
    widget.set_snapshot(_snapshot())
    before = widget.definition()
    errors = []
    widget.discovery_failed.connect(errors.append)

    widget.refresh()

    assert widget.definition() == before
    assert errors == ["NI-DAQmx is unavailable"]
    assert "unavailable" in widget.status_label.text()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
