"""Focused tests for the Kepco BOP-GL magnet-supply driver."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments import KepcoBOPGL
from stoner_measurement.instruments.magnet_controller import MagnetLimits, MagnetState
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport
from stoner_measurement.magnet_control.engine import MagnetControllerEngine


def _null(responses=None):
    """Return an open NullTransport pre-loaded with responses."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestKepcoBOPGL:
    def test_defaults_to_scpi_and_parses_identity(self):
        transport = _null(
            [
                b"KEPCO,BOP 20-50GL,SN001,3.05\n",
                b"KEPCO,BOP 20-50GL,SN001,3.05\n",
            ]
        )
        supply = KepcoBOPGL(transport)

        assert isinstance(supply.protocol, ScpiProtocol)
        assert supply.get_model() == "BOP 20-50GL"
        assert supply.get_firmware_version() == "3.05"

    def test_field_conversion_is_local_driver_state(self):
        transport = _null([b"2.5\n"])
        supply = KepcoBOPGL(transport)

        supply.set_magnet_constant(0.2)

        assert supply.field == pytest.approx(0.5)
        assert transport.write_log == [b"MEAS:CURR?\n"]

    def test_field_target_and_rate_convert_to_current(self):
        supply = KepcoBOPGL(_null())
        supply.set_magnet_constant(0.2)

        supply.set_target_field(0.6)
        supply.set_ramp_rate_field(0.4)

        assert supply.target_current == pytest.approx(3.0)
        assert supply.target_field == pytest.approx(0.6)
        assert supply.ramp_rate_current == pytest.approx(2.0)
        assert supply.ramp_rate_field == pytest.approx(0.4)

    def test_compliance_voltage_uses_voltage_protection(self):
        transport = _null([b"+5.0,-4.0\n"])
        supply = KepcoBOPGL(transport)

        supply.set_compliance_voltage(3.5)

        assert supply.compliance_voltage == pytest.approx(5.0)
        assert transport.write_log == [
            b"VOLT:PROT:MODE FIX\n",
            b"VOLT:PROT 3.5\n",
            b"VOLT:PROT?\n",
        ]

    def test_set_limits_programs_current_limit_and_derives_field_limit(self):
        transport = _null()
        supply = KepcoBOPGL(transport)
        supply.set_magnet_constant(0.1)

        supply.set_limits(MagnetLimits(max_current=50.0, max_field=4.0, max_ramp_rate=1.0))

        assert supply._limits == MagnetLimits(  # noqa: SLF001
            max_current=40.0,
            max_field=4.0,
            max_ramp_rate=1.0,
        )
        assert transport.write_log == [b"CURR:LIM 40\n"]

    def test_ramp_builds_timed_list_from_measured_current(self):
        transport = _null([b"0.0\n"])
        supply = KepcoBOPGL(transport)
        supply.set_ramp_rate_current(6.0)
        supply.set_target_current(0.0034)

        supply.ramp_to_target()

        assert transport.write_log == [
            b"MEAS:CURR?\n",
            b"LIST:CLE\n",
            b"LIST:CURR 0,0.0034\n",
            b"LIST:DWEL 0.034\n",
            b"LIST:COUN 1\n",
            b"CURR:MODE LIST\n",
        ]

    def test_list_upload_commands_stay_below_transport_limit(self):
        transport = _null([b"0.0\n"])
        supply = KepcoBOPGL(transport)
        supply.set_ramp_rate_current(60.0)
        supply.set_target_current(1.0)

        supply.ramp_to_target()

        list_commands = [
            command for command in transport.write_log if command.startswith(b"LIST:CURR ")
        ]
        assert len(list_commands) > 1
        assert all(len(command.rstrip(b"\n")) <= 240 for command in list_commands)

    def test_status_reports_list_running_and_no_heater(self):
        transport = _null([b"16384\n", b"0\n", b"1\n", b"0.5\n", b"0.2\n"])
        supply = KepcoBOPGL(transport)
        supply.set_magnet_constant(0.1)
        supply.set_target_current(1.0)
        supply.set_ramp_rate_current(1.0)

        status = supply.status

        assert status.state is MagnetState.RAMPING
        assert status.field == pytest.approx(0.05)
        assert status.heater_on is None
        assert supply.heater is False

    def test_heater_commands_are_explicitly_unsupported(self):
        supply = KepcoBOPGL(_null())
        with pytest.raises(NotImplementedError, match="no persistent-switch heater"):
            supply.heater_on()
        with pytest.raises(NotImplementedError, match="no persistent-switch heater"):
            supply.heater_off()

    def test_engine_selects_scpi_protocol(self):
        engine = MagnetControllerEngine()
        try:
            assert isinstance(engine._build_protocol("KepcoBOPGL"), ScpiProtocol)  # noqa: SLF001
        finally:
            engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
