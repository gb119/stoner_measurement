"""Controller ownership, compatibility and failure isolation contracts."""

import time
from dataclasses import replace

import pytest

from stoner_measurement.instruments.simulated import SimulatedTemperatureController
from stoner_measurement.instruments.temperature_controller import ControlMode, SensorStatus
from stoner_measurement.temperature_control import engine as engine_module
from stoner_measurement.temperature_control.config import normalise_configuration
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.temperature_control.references import (
    ChannelRef,
    LoopRef,
    channel_ref,
    loop_ref,
)
from stoner_measurement.temperature_control.types import (
    EngineStatus,
    StabilityBand,
    StabilityConfig,
)


@pytest.fixture
def rig(monkeypatch, qapp):
    monkeypatch.setattr(engine_module, "load_temperature_controller_config", lambda: {})
    engine = TemperatureControllerEngine()
    engine.set_polling_rate(0)
    monkeypatch.setattr(TemperatureControllerEngine, "_singleton", engine)
    yield engine
    engine.shutdown()


def connect_pair(rig):
    primary = SimulatedTemperatureController()
    secondary = SimulatedTemperatureController()
    rig.connect_instrument(primary)
    rig.connect_instrument(secondary, controller_id="secondary")
    return primary, secondary


def test_optional_secondary_and_legacy_configuration(rig):
    assert not rig.controller_enabled("secondary")
    assert rig.connected_driver is None
    rig.connect_instrument(SimulatedTemperatureController())
    assert rig.read_controller_state().readings["A"].value == pytest.approx(300)
    assert rig.controller("secondary").connected_driver is None
    with pytest.raises(RuntimeError, match="disabled"):
        rig.ensure_controller("secondary")
    legacy = normalise_configuration(
        {"connection": {"driver": "old"}, "stability": {"tolerance_k": 0.3}}
    )
    assert legacy["controllers"]["primary"]["connection"]["driver"] == "old"
    modern = normalise_configuration(
        {**legacy, "controllers": {"primary": {"connection": {"driver": "new"}}}}
    )
    assert modern["connection"]["driver"] == "new"


def test_overlapping_channels_and_loops_route_independently(rig):
    primary, secondary = connect_pair(rig)
    rig.set_setpoint(1, 310)
    rig.set_setpoint(LoopRef("secondary", 1), 280)
    rig.set_ramp(LoopRef("secondary", 1), 7, True)
    rig.set_input_channel(LoopRef("secondary", 1), ChannelRef("secondary", "B"))
    state = rig.read_controller_state()
    assert primary.get_setpoint(1) == 310
    assert secondary.get_setpoint(1) == 280
    assert primary.get_ramp_rate(1) == 10
    assert secondary.get_ramp_rate(1) == 7
    assert state.setpoints[1] == 310
    assert state.loop_values("setpoints")[LoopRef("secondary", 1)] == 280
    assert len(state.all_readings) == 8
    assert len(rig.loop_catalogue()) == 4
    assert len(rig.channel_catalogue()) == 8


def test_invalid_assignment_writes_nothing(rig):
    primary, secondary = connect_pair(rig)
    with pytest.raises(ValueError, match="cannot control"):
        rig.set_all_loop_settings(
            LoopRef("secondary", 1),
            input_channel=ChannelRef("primary", "A"),
            setpoint=900,
            mode=ControlMode.OFF,
            ramp_enabled=False,
            ramp_rate=1,
            pid_p=1,
            pid_i=1,
            pid_d=1,
            heater_range=0,
        )
    assert secondary.get_setpoint(1) == 300
    assert primary.get_setpoint(1) == 300


def test_restricted_loop_inputs(rig, monkeypatch):
    _, secondary = connect_pair(rig)
    monkeypatch.setattr(secondary, "get_loop_input_channels", lambda loop: ("B",))
    assert rig.loop_input_channels(LoopRef("secondary", 1)) == (ChannelRef("secondary", "B"),)
    with pytest.raises(ValueError):
        rig.set_input_channel(LoopRef("secondary", 1), ChannelRef("secondary", "A"))


def test_failed_peer_does_not_erase_primary_or_report_stability(rig, monkeypatch):
    _, secondary = connect_pair(rig)
    rig.set_stability_config(StabilityConfig(window_s=0))
    rig.controller("secondary").set_stability_config(StabilityConfig(window_s=0))
    assert rig.read_controller_state().secondary.stable[1]
    count = len(rig._history["A"])

    def fail(_channel):
        raise ConnectionError("unplugged")

    monkeypatch.setattr(secondary, "get_temperature_reading", fail)
    state = rig.read_controller_state()
    assert state.engine_status is EngineStatus.ERROR
    assert state.readings["A"].value == pytest.approx(300)
    assert not state.secondary.stable
    assert len(rig._history["A"]) == count + 1
    assert not rig.controller("secondary")._at_setpoint_since


def test_stale_or_invalid_sensor_cannot_complete_wait(rig, monkeypatch):
    primary, _ = connect_pair(rig)
    rig.set_stability_config(StabilityConfig(window_s=0))
    assert rig.read_controller_state().stable[1]
    rig._latest_state_time = time.monotonic() - 20
    assert not rig.get_engine_state().stable[1]
    monkeypatch.setattr(primary, "get_sensor_status", lambda channel: SensorStatus.FAULT)
    assert not rig.read_controller_state().stable[1]
    rig.set_stability_config(
        StabilityConfig(bands=[StabilityBand(tolerance_channel="missing", window_s=0)])
    )
    assert not rig.read_controller_state().stable[1]


def test_secondary_survives_primary_disconnect(rig):
    _, secondary = connect_pair(rig)
    rig.read_controller_state()
    count = len(rig.controller("secondary")._history["A"])
    rig.disconnect_instrument()
    assert secondary.is_connected
    state = rig.read_controller_state()
    assert not state.readings
    assert state.secondary.readings
    assert len(rig.controller("secondary")._history["A"]) == count + 1
    rig.set_setpoint(LoopRef("secondary", 1), 270)
    with pytest.raises(RuntimeError):
        rig.set_setpoint(1, 280)


def test_reconnect_resets_only_replaced_session(rig):
    primary, old = connect_pair(rig)
    rig.read_controller_state()
    count = len(rig._history["A"])
    rig.connect_instrument(SimulatedTemperatureController(), controller_id="secondary")
    assert not old.is_connected
    assert primary.is_connected
    assert len(rig._history["A"]) == count
    assert not rig.controller("secondary").get_engine_state().readings


def test_cleanup_failure_aborts_replacement_and_shutdown_attempts_peer(rig, monkeypatch):
    primary, secondary = connect_pair(rig)
    original = primary.disconnect

    def fail():
        raise ConnectionError("cleanup failed")

    monkeypatch.setattr(primary, "disconnect", fail)
    candidate = SimulatedTemperatureController()
    with pytest.raises(ConnectionError):
        rig.connect_instrument(candidate)
    assert not candidate.is_connected
    with pytest.raises(ExceptionGroup):
        rig.shutdown()
    assert not secondary.is_connected
    monkeypatch.setattr(primary, "disconnect", original)


def test_partial_connection_is_cleaned(rig, monkeypatch):
    driver = SimulatedTemperatureController()
    original = driver.connect

    def fail():
        original()
        raise ConnectionError("identification failed")

    monkeypatch.setattr(driver, "connect", fail)
    with pytest.raises(ConnectionError):
        rig.connect_instrument(driver)
    assert not driver.is_connected
    assert rig.connected_driver is None
    assert rig.status is EngineStatus.ERROR


def test_duplicate_connection_rejected_but_null_instances_allowed(rig):
    connect_pair(rig)
    rig._connected_transport_name = "Serial"
    rig._connected_address = "port=COM7;baud=9600"
    with pytest.raises(ValueError, match="already owns"):
        rig._check_connection("secondary", "serial", "baud=19200;port=com7")
    rig._check_connection("secondary", "Null (test)", "")


def test_noncontiguous_loops_and_different_capabilities(rig, monkeypatch):
    primary, secondary = connect_pair(rig)
    caps = replace(
        secondary.get_capabilities(),
        loop_numbers=(2,),
        num_loops=1,
        input_channels=("B",),
        num_inputs=1,
        min_temperature=10,
        max_temperature=200,
    )
    monkeypatch.setattr(secondary, "get_capabilities", lambda: caps)
    assert [d.reference for d in rig.loop_catalogue()] == [
        LoopRef("primary", 1),
        LoopRef("primary", 2),
        LoopRef("secondary", 2),
    ]
    rig.set_setpoint(LoopRef("secondary", 2), 150)
    with pytest.raises(ValueError):
        rig.set_setpoint(LoopRef("secondary", 1), 150)
    assert primary.get_setpoint(1) == 300


@pytest.mark.parametrize(
    "value", [{"controller_id": "third", "loop": 1}, {"controller_id": "secondary", "loop": 0}]
)
def test_bad_references_are_rejected(value):
    with pytest.raises(ValueError):
        loop_ref(value)


def test_reference_json_round_trip():
    ref = ChannelRef("secondary", "A")
    assert channel_ref(ref.to_json()) == ref
    assert loop_ref(1) == LoopRef("primary", 1)


def test_new_target_invalidates_cached_stability(rig):
    primary, _ = connect_pair(rig)
    rig.set_stability_config(StabilityConfig(window_s=0))
    assert rig.read_controller_state().stable[1]
    rig.set_setpoint(1, 325)
    assert primary.get_setpoint(1) == 325
    assert not rig.get_engine_state().stable[1]
    assert rig._at_setpoint_since[1] is None


def test_zone_write_without_owner_is_an_error(rig):
    assert rig.get_zone_table(1) is None
    with pytest.raises(RuntimeError, match="disconnected"):
        rig.set_zone_table(1, [])


def test_failed_primary_replacement_keeps_secondary_polling(rig, monkeypatch):
    connect_pair(rig)
    rig.set_polling_rate(2)
    candidate = SimulatedTemperatureController()

    def fail():
        raise ConnectionError("unavailable primary")

    monkeypatch.setattr(candidate, "connect", fail)
    with pytest.raises(ConnectionError):
        rig.connect_instrument(candidate)
    assert rig._timer.isActive()
    assert rig.read_controller_state().secondary.readings


def test_secondary_cleanup_failure_retains_service_for_retry(rig, monkeypatch):
    primary, secondary = connect_pair(rig)
    original = secondary.disconnect

    def fail():
        raise ConnectionError("secondary cleanup failed")

    monkeypatch.setattr(secondary, "disconnect", fail)
    with pytest.raises(ExceptionGroup):
        rig.shutdown()
    assert not primary.is_connected
    assert TemperatureControllerEngine.instance() is rig
    assert rig.controller("secondary").connected_driver is secondary
    monkeypatch.setattr(secondary, "disconnect", original)
    rig.shutdown()
    assert not secondary.is_connected


def test_yaml_round_trip_preserves_both_unconnected_settings(rig, monkeypatch, tmp_path):
    import yaml

    from stoner_measurement.temperature_control import config as config_module

    target = tmp_path / "temperature_controller.yaml"
    monkeypatch.setattr(config_module, "machine_config_path", lambda: target)
    rig.preferred_driver_name = "PrimaryDriver"
    secondary = rig.controller("secondary")
    secondary.preferred_driver_name = "SecondaryDriver"
    secondary.preferred_transport_name = "Serial"
    secondary.preferred_address = "port=COM9;baud=19200"
    rig.set_controller_enabled("secondary", True)
    secondary.set_stability_config(StabilityConfig(bands=[StabilityBand(tolerance_channel="B")]))
    rig.save_configuration()
    saved = yaml.safe_load(target.read_text())
    assert saved["controllers"]["secondary"]["connection"]["address"] == "port=COM9;baud=19200"
    monkeypatch.setattr(engine_module, "load_temperature_controller_config", lambda: saved)
    restored = TemperatureControllerEngine()
    try:
        assert restored.controller_enabled("secondary")
        assert restored.controller("secondary").preferred_driver_name == "SecondaryDriver"
        assert restored.controller("secondary").stability_config.bands[0].tolerance_channel == "B"
        assert all(session.connected_driver is None for session in restored.controllers.values())
    finally:
        restored.shutdown()


def test_legacy_machine_settings_override_new_bundled_defaults(monkeypatch, tmp_path):
    import yaml

    from stoner_measurement.temperature_control import config as config_module

    bundled = tmp_path / "bundled.yaml"
    machine = tmp_path / "machine.yaml"
    bundled.write_text(
        yaml.safe_dump(
            {
                "controllers": {
                    "primary": {"connection": {"driver": ""}},
                    "secondary": {"enabled": False},
                }
            }
        )
    )
    machine.write_text(
        yaml.safe_dump(
            {
                "connection": {"driver": "LegacyRig", "address": "COM5"},
                "stability": {"tolerance_k": 0.25},
            }
        )
    )
    monkeypatch.setattr(config_module, "bundled_resource_path", lambda *args: bundled)
    monkeypatch.setattr(config_module, "machine_config_path", lambda: machine)
    loaded = config_module.load_temperature_controller_config()
    assert loaded["controllers"]["primary"]["connection"]["driver"] == "LegacyRig"
    assert loaded["connection"]["address"] == "COM5"
    assert loaded["controllers"]["primary"]["stability"]["tolerance_k"] == 0.25
    assert not loaded["controllers"]["secondary"]["enabled"]


@pytest.mark.parametrize("reader", ["primary", "secondary"])
def test_cross_controller_criteria_read_complete_cycle(rig, monkeypatch, reader):
    primary, secondary = connect_pair(rig)
    original = secondary.get_temperature_reading
    monkeypatch.setattr(
        secondary, "get_temperature_reading", lambda channel: replace(original(channel), value=310)
    )
    rig.set_setpoint(1, 310)
    rig.set_setpoint(LoopRef("secondary", 1), 310)
    rig.set_stability_config(
        StabilityConfig(
            bands=[
                StabilityBand(
                    tolerance_channel="secondary:A", rate_channel="secondary:A", window_s=0
                )
            ]
        )
    )
    state = rig.controller(reader).read_controller_state()
    assert state.stable[1]
    assert rig.get_engine_state().stable[1]
    assert rig.controller("secondary").get_engine_state().stable[1]
    assert rig.get_engine_state().stability_rate_channel == "secondary:A"
    assert primary.get_setpoint(1) == 310


def test_cross_controller_disconnect_and_stale_cache_invalidate_wait(rig):
    connect_pair(rig)
    rig.set_stability_config(
        StabilityConfig(
            bands=[
                StabilityBand(
                    tolerance_channel="secondary:A", rate_channel="secondary:A", window_s=0
                )
            ]
        )
    )
    assert rig.read_controller_state().stable[1]
    secondary = rig.controller("secondary")
    secondary._latest_state_time = time.monotonic() - 20
    assert not rig.get_engine_state().stable[1]
    assert 1 not in rig._at_setpoint_since
    assert rig.read_controller_state().stable[1]
    secondary.disconnect_instrument()
    assert not rig.get_engine_state().stable[1]
    assert rig.get_engine_state().stability_rate_channel == "secondary:A"


def test_first_matching_band_keeps_priority_and_yaml_order(rig, monkeypatch):
    primary, _ = connect_pair(rig)
    original = primary.get_temperature_reading
    monkeypatch.setattr(
        primary, "get_temperature_reading", lambda channel: replace(original(channel), value=280)
    )
    first = StabilityBand(
        max_temperature_k=500,
        tolerance_channel="secondary:A",
        rate_channel="secondary:A",
        window_s=0,
    )
    second = StabilityBand(
        max_temperature_k=400, tolerance_channel="A", rate_channel="A", window_s=0
    )
    rig.set_stability_config(StabilityConfig(bands=[first, second]))
    assert rig.read_controller_state().stable[1]
    assert rig.get_engine_state().stability_rate_channel == "secondary:A"
    config = rig.configuration_dict()
    assert config["schema_version"] == 3
    assert [band["max_temperature_k"] for band in config["stability"]["bands"]] == [500, 400]
    assert "stability" not in config["controllers"]["secondary"]
    rig.set_stability_config(StabilityConfig(bands=[second, first]))
    assert not rig.get_engine_state().stable[1]
    assert not rig.read_controller_state().stable[1]
    assert rig.get_engine_state().stability_rate_channel == "A"


def test_chart_rate_uses_first_active_band_across_loops(rig):
    connect_pair(rig)
    rig.set_setpoint(LoopRef("secondary", 1), 80)
    rig.set_stability_config(
        StabilityConfig(
            bands=[
                StabilityBand(max_temperature_k=100, rate_channel="secondary:B"),
                StabilityBand(max_temperature_k=1000, rate_channel="A"),
            ]
        )
    )
    state = rig.read_controller_state()
    assert state.stability_rate_channels[1] == "A"
    assert state.secondary.stability_rate_channels[1] == "secondary:B"
    assert state.stability_rate_channel == "secondary:B"


def test_default_sensor_change_invalidates_existing_stability(rig):
    connect_pair(rig)
    rig.set_stability_config(StabilityConfig(window_s=0))
    assert rig.read_controller_state().secondary.stable[1]
    rig.disconnect_instrument()
    assert not rig.controller("secondary").get_engine_state().stable[1]
    assert rig.read_controller_state().secondary.stable[1]


def test_shared_config_migration_prefers_primary_then_explicit_shared():
    legacy = {
        "schema_version": 2,
        "controllers": {
            "primary": {"stability": {"tolerance_k": 0.1}},
            "secondary": {"stability": {"tolerance_k": 0.9}},
        },
    }
    assert normalise_configuration(legacy)["stability"]["tolerance_k"] == 0.1
    modern = {**legacy, "schema_version": 3, "stability": {"tolerance_k": 0.4}}
    assert normalise_configuration(modern)["stability"]["tolerance_k"] == 0.4


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
