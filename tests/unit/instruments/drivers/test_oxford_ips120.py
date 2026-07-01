"""Focused tests for the Oxford IPS120 magnet controller driver."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.magnet_controller import (
    HeaterState,
    MagnetState,
    MagnetStatus,
)
from stoner_measurement.instruments.oxford import OxfordIPS120
from stoner_measurement.instruments.protocol import OxfordProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestOxfordIPS120:
    def test_default_protocol_is_oxford(self):
        m = OxfordIPS120(transport=NullTransport())
        assert isinstance(m.protocol, OxfordProtocol)

    def test_identity_parsing(self):
        t = _null(
            responses=[
                b"VIPS120-10 3.07\r",
                b"VIPS120-10 3.07\r",
                b"VIPS120-10 3.07\r",
            ]
        )
        m = OxfordIPS120(transport=t)
        assert m.identify() == "IPS120-10 3.07"
        assert m.get_model() == "IPS120-10"
        assert m.get_firmware_version() == "3.07"

    def test_reading_properties_send_correct_commands(self):
        t = _null(responses=[b"R2.5\r", b"R0.75\r", b"R1.2\r"])
        m = OxfordIPS120(transport=t)
        assert m.current == pytest.approx(2.5)
        assert m.field == pytest.approx(0.75)
        assert m.voltage == pytest.approx(1.2)
        assert t.write_log == [b"R1\r", b"R7\r", b"R2\r"]

    def test_set_target_and_ramp_commands(self):
        t = _null()
        m = OxfordIPS120(transport=t)
        m.set_target_current(3.0)
        m.set_ramp_rate_current(0.2)
        m.ramp_to_target()
        assert t.write_log == [b"I3.0\r", b"S0.2\r", b"A1\r"]

    def test_heater_methods_and_property(self):
        t = _null(responses=[b"X00A0C0H1P0\r"])
        m = OxfordIPS120(transport=t)
        m.heater_on()
        m.heater_off()
        assert m.heater is True
        assert t.write_log == [b"H1\r", b"H0\r", b"X\r"]

    def test_status_maps_state(self):
        t = _null(
            responses=[
                b"X00A0C0H0P1\r",
                b"R1.1\r",
                b"R0.3\r",
                b"R0.2\r",
            ]
        )
        m = OxfordIPS120(transport=t)
        status = m.status
        assert status.state.value == "standby"
        assert status.at_target is True
        assert status.current == pytest.approx(1.1)
        assert status.field == pytest.approx(0.3)
        assert status.voltage == pytest.approx(0.2)
        assert status.heater_on is False
        assert status.persistent is True
        assert t.write_log == [b"X\r", b"R1\r", b"R7\r", b"R2\r"]

    def test_set_magnet_constant_validation(self):
        m = OxfordIPS120(transport=_null())
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(0.0)
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(-1.0)
        m.set_magnet_constant(0.5)
        assert m.magnet_constant == pytest.approx(0.5)

    def test_set_target_field_uses_magnet_constant_conversion(self):
        t = _null()
        m = OxfordIPS120(transport=t)
        m.set_magnet_constant(0.5)
        m.set_target_field(1.0)
        assert t.write_log == [b"I2.0\r"]

    def test_query_float_raises_for_unparseable_numeric_response(self):
        t = _null(responses=[b"Rnot-a-float\r"])
        m = OxfordIPS120(transport=t)
        with pytest.raises(ValueError, match=r"Invalid numeric response for R1"):
            _ = m.current

    def test_wait_for_ramp_raises_timeout_when_stuck_ramping(self, monkeypatch):
        m = OxfordIPS120(transport=_null())

        def _always_ramping(_self):
            return MagnetStatus(
                state=MagnetState.RAMPING,
                current=0.0,
                field=0.0,
                voltage=0.0,
                persistent=False,
                heater_on=False,
                heater_state=HeaterState.OFF,
                at_target=False,
                message="X00A1C0H0P0",
            )

        monkeypatch.setattr(OxfordIPS120, "status", property(_always_ramping))
        with pytest.raises(TimeoutError):
            m._wait_for_ramp_complete(timeout=0.01, poll_period=0.0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
