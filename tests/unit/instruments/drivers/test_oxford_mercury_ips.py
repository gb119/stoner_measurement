"""Focused tests for the Oxford Mercury iPS magnet controller driver."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.magnet_controller import (
    HeaterState,
    MagnetState,
    MagnetStatus,
)
from stoner_measurement.instruments.oxford import OxfordMercuryIPS
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestOxfordMercuryIPS:
    def test_default_protocol_is_scpi(self):
        m = OxfordMercuryIPS(transport=NullTransport())
        assert isinstance(m.protocol, ScpiProtocol)

    def test_default_uid(self):
        m = OxfordMercuryIPS(transport=NullTransport())
        assert m._uid == "PSU.M1"

    def test_custom_uid(self):
        m = OxfordMercuryIPS(transport=NullTransport(), device_uid="PSU.M2")
        assert m._uid == "PSU.M2"

    def test_identity_and_model_and_firmware(self):
        t = _null(
            responses=[
                b"Oxford Instruments,Mercury iPS,12345,2.7.0\n",
                b"Oxford Instruments,Mercury iPS,12345,2.7.0\n",
                b"Oxford Instruments,Mercury iPS,12345,2.7.0\n",
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        assert m.identify() == "Oxford Instruments,Mercury iPS,12345,2.7.0"
        assert m.get_model() == "Mercury iPS"
        assert m.get_firmware_version() == "2.7.0"

    def test_field_current_voltage_properties(self):
        uid = "PSU.M1"
        t = _null(
            responses=[
                b"STAT:DEV:PSU.M1:PSU:SIG:FLD:+1.50000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:CURR:+2.00000A\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:VOLT:+0.12345V\n",
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        assert m.field == pytest.approx(1.5)
        assert m.current == pytest.approx(2.0)
        assert m.voltage == pytest.approx(0.12345)
        assert t.write_log == [
            f"READ:DEV:{uid}:PSU:SIG:FLD\n".encode(),
            f"READ:DEV:{uid}:PSU:SIG:CURR\n".encode(),
            f"READ:DEV:{uid}:PSU:SIG:VOLT\n".encode(),
        ]

    def test_heater_property_on(self):
        t = _null(responses=[b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:ON\n"])
        m = OxfordMercuryIPS(transport=t)
        assert m.heater is True

    def test_heater_property_off(self):
        t = _null(responses=[b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:OFF\n"])
        m = OxfordMercuryIPS(transport=t)
        assert m.heater is False

    def test_heater_on_off_commands(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.heater_on()
        m.heater_off()
        assert t.write_log == [
            b"SET:DEV:PSU.M1:PSU:SIG:SWHT:ON\n",
            b"SET:DEV:PSU.M1:PSU:SIG:SWHT:OFF\n",
        ]

    def test_set_target_field_command(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.set_target_field(1.0)
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:SIG:FSET:1.000000\n"]

    def test_set_target_current_uses_magnet_constant(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.set_magnet_constant(0.5)
        m.set_target_current(2.0)
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:SIG:FSET:1.000000\n"]

    def test_set_ramp_rate_field_command(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.set_ramp_rate_field(0.1)
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:SIG:RSET:0.100000\n"]

    def test_set_ramp_rate_current_uses_magnet_constant(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.set_magnet_constant(0.5)
        m.set_ramp_rate_current(0.2)
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:SIG:RSET:0.100000\n"]

    def test_set_ramp_rate_negative_raises(self):
        m = OxfordMercuryIPS(transport=_null())
        with pytest.raises(ValueError, match="non-negative"):
            m.set_ramp_rate_field(-0.1)
        with pytest.raises(ValueError, match="non-negative"):
            m.set_ramp_rate_current(-0.1)

    def test_ramp_to_target_command(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.ramp_to_target()
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:ACTN:RTOS\n"]

    def test_pause_ramp_command(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.pause_ramp()
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:ACTN:HOLD\n"]

    def test_abort_ramp_command(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.abort_ramp()
        assert t.write_log == [b"SET:DEV:PSU.M1:PSU:ACTN:HOLD\n"]

    def test_ramp_to_field_sends_correct_commands(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.ramp_to_field(1.5)
        assert t.write_log == [
            b"SET:DEV:PSU.M1:PSU:SIG:FSET:1.500000\n",
            b"SET:DEV:PSU.M1:PSU:ACTN:RTOS\n",
        ]

    def test_ramp_to_current_sends_correct_commands(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t)
        m.set_magnet_constant(0.5)
        m.ramp_to_current(2.0)
        assert t.write_log == [
            b"SET:DEV:PSU.M1:PSU:SIG:FSET:1.000000\n",
            b"SET:DEV:PSU.M1:PSU:ACTN:RTOS\n",
        ]

    def test_set_magnet_constant_validation(self):
        m = OxfordMercuryIPS(transport=_null())
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(0.0)
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(-1.0)
        m.set_magnet_constant(0.5)
        assert m.magnet_constant == pytest.approx(0.5)

    def test_status_ramping(self):
        t = _null(
            responses=[
                b"STAT:DEV:PSU.M1:PSU:ACTN:RTOS\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:STAF:NORM\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FLD:+0.50000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:CURR:+1.00000A\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:VOLT:+0.05000V\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FSET:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:ON\n",                
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        status = m.status
        assert status.state == MagnetState.RAMPING
        assert status.field == pytest.approx(0.5)
        assert status.current == pytest.approx(1.0)
        assert status.voltage == pytest.approx(0.05)
        assert status.at_target is False
        assert status.heater_on is True
        assert status.heater_state.value == "on"
        assert status.persistent is False

    def test_status_at_target_when_hold_and_field_matches(self):
        t = _null(
            responses=[
                b"STAT:DEV:PSU.M1:PSU:ACTN:HOLD\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:STAF:NORM\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FLD:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:CURR:+2.00000A\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:VOLT:+0.00001V\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FSET:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:ON\n",                
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        status = m.status
        assert status.state == MagnetState.AT_TARGET
        assert status.at_target is True

    def test_status_standby_when_hold_but_field_differs(self):
        t = _null(
            responses=[
                b"STAT:DEV:PSU.M1:PSU:ACTN:HOLD\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:STAF:NORM\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FLD:+0.50000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:CURR:+1.00000A\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:VOLT:+0.00001V\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FSET:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:ON\n",
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        status = m.status
        assert status.state == MagnetState.STANDBY
        assert status.at_target is False

    def test_status_persistent_when_heater_off(self):
        t = _null(
            responses=[
                b"STAT:DEV:PSU.M1:PSU:ACTN:HOLD\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:STAF:NORM\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FLD:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:CURR:+0.00000A\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:VOLT:+0.00000V\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:FSET:+1.00000T\n",
                b"STAT:DEV:PSU.M1:PSU:SIG:SWHT:OFF\n",
            ]
        )
        m = OxfordMercuryIPS(transport=t)
        status = m.status
        assert status.persistent is True
        assert status.heater_on is False
        assert status.heater_state.value == "off"

    def test_read_sig_float_raises_on_invalid_response(self):
        t = _null(responses=[b"STAT:DEV:PSU.M1:PSU:SIG:FLD:NOT_A_NUMBER\n"])
        m = OxfordMercuryIPS(transport=t)
        with pytest.raises(ValueError, match="FLD"):
            _ = m.field

    def test_wait_for_ramp_raises_timeout_when_stuck_ramping(self, monkeypatch):
        m = OxfordMercuryIPS(transport=_null())

        def _always_ramping(_self):
            return MagnetStatus(
                state=MagnetState.RAMPING,
                current=0.0,
                field=0.0,
                voltage=0.0,
                persistent=False,
                heater_on=True,
                heater_state=HeaterState.ON,
                at_target=False,
                persistent_field=None,
            )

        monkeypatch.setattr(OxfordMercuryIPS, "status", property(_always_ramping))
        with pytest.raises(TimeoutError):
            m._wait_for_ramp_complete(timeout=0.01, poll_period=0.0)

    def test_custom_uid_in_commands(self):
        t = _null()
        m = OxfordMercuryIPS(transport=t, device_uid="PSU.M2")
        m.set_target_field(1.0)
        m.ramp_to_target()
        m.pause_ramp()
        m.heater_on()
        assert t.write_log == [
            b"SET:DEV:PSU.M2:PSU:SIG:FSET:1.000000\n",
            b"SET:DEV:PSU.M2:PSU:ACTN:RTOS\n",
            b"SET:DEV:PSU.M2:PSU:ACTN:HOLD\n",
            b"SET:DEV:PSU.M2:PSU:SIG:SWHT:ON\n",
        ]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
