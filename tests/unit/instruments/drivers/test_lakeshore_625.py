"""Focused tests for the Lakeshore 625 magnet controller driver."""

from __future__ import annotations

import logging

import pytest

from stoner_measurement.instruments.lakeshore import Lakeshore525, Lakeshore625
from stoner_measurement.instruments.magnet_controller import (
    HeaterState,
    MagnetLimits,
    MagnetState,
    MagnetStatus,
)
from stoner_measurement.instruments.protocol import LakeshoreProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestLakeshore625:
    def test_default_protocol_is_lakeshore(self):
        m = Lakeshore625(transport=NullTransport())
        assert isinstance(m.protocol, LakeshoreProtocol)

    def test_identify_and_model_and_firmware(self):
        t = _null(
            responses=[
                b"LAKESHORE,MODEL625,SN001,1.2.3\r\n",
                b"LAKESHORE,MODEL625,SN001,1.2.3\r\n",
                b"LAKESHORE,MODEL625,SN001,1.2.3\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        assert m.identify() == "LAKESHORE,MODEL625,SN001,1.2.3"
        assert m.get_model() == "MODEL625"
        assert m.get_firmware_version() == "1.2.3"

    def test_reading_properties_send_correct_commands(self):
        t = _null(responses=[b"2.5\r\n", b"0.75\r\n", b"1.2\r\n"])
        m = Lakeshore625(transport=t)
        assert m.current == pytest.approx(2.5)
        assert m.field == pytest.approx(0.75)
        assert m.voltage == pytest.approx(1.2)
        assert t.write_log == [b"RDGI?\r\n", b"RDGF?\r\n", b"RDGV?\r\n"]

    def test_current_uses_first_value_from_comma_separated_response(self):
        t = _null(responses=[b"2.5,OK\r\n"])
        m = Lakeshore625(transport=t)
        assert m.current == pytest.approx(2.5)

    def test_set_target_and_ramp_commands(self):
        t = _null()
        m = Lakeshore625(transport=t)
        m.set_target_current(3.0)
        m.set_target_field(0.9)
        m.ramp_to_target()
        assert t.write_log == [b"SETI 3.0\r\n", b"SETF 0.9\r\n", b"RAMP\r\n"]

    def test_ramp_rate_current_query_uses_rate_in_a_per_s(self):
        t = _null(responses=[b"0.5\r\n"])
        m = Lakeshore625(transport=t)
        assert m.ramp_rate_current == pytest.approx(30.0)
        assert t.write_log == [b"RATE?\r\n"]

    def test_ramp_rate_field_query_uses_rate_in_a_per_s(self):
        t = _null(responses=[b"0.1\r\n"])
        m = Lakeshore625(transport=t)
        m._magnet_constant = 0.075  # noqa: SLF001
        assert m.ramp_rate_field == pytest.approx(0.45)
        assert t.write_log == [b"RATE?\r\n"]

    def test_set_ramp_rate_current_writes_rate_in_a_per_s(self):
        t = _null()
        m = Lakeshore625(transport=t)
        m.set_ramp_rate_current(30.0)
        assert t.write_log == [b"RATE 0.5\r\n"]

    def test_set_ramp_rate_field_writes_rate_in_a_per_s(self):
        t = _null()
        m = Lakeshore625(transport=t)
        m.set_magnet_constant(0.075)
        m.set_ramp_rate_field(0.45)
        assert t.write_log == [b"FLDS 0,0.075\r\n", b"RATE 0.1\r\n"]

    def test_set_ramp_rate_field_requires_positive_magnet_constant(self):
        m = Lakeshore625(transport=_null())
        m._magnet_constant = 0.0  # noqa: SLF001
        with pytest.raises(ValueError, match="Magnet constant must be positive"):
            m.set_ramp_rate_field(0.45)

    def test_pause_hold_zero_and_abort_commands(self):
        t = _null()
        m = Lakeshore625(transport=t)
        m.pause_ramp()
        m.hold()
        m.go_to_zero()
        m.abort_ramp()
        assert t.write_log == [b"STOP\r\n", b"STOP\r\n", b"ZERO\r\n", b"STOP\r\n"]

    def test_heater_methods_and_property(self):
        t = _null(responses=[b"1\r\n"])
        m = Lakeshore625(transport=t)
        m.heater_on()
        m.heater_off()
        assert m.heater is True
        assert t.write_log == [b"PSH 1\r\n", b"PSH 0\r\n", b"PSH?\r\n"]

    def test_heater_property_false_during_transition(self):
        t = _null(responses=[b"2\r\n", b"3\r\n"])
        m = Lakeshore625(transport=t)
        assert m.heater is False
        assert m.heater is False
        assert t.write_log == [b"PSH?\r\n", b"PSH?\r\n"]

    def test_status_maps_heater_transition_states(self):
        for psh_reply, expected in ((b"2\r\n", HeaterState.COOLING), (b"3\r\n", HeaterState.WARMING)):
            t = _null(responses=[b"2\r\n", psh_reply, b"1.1\r\n", b"0.3\r\n", b"0.2\r\n"])
            m = Lakeshore625(transport=t)
            status = m.status
            assert status.heater_state is expected
            assert status.heater_on is False

    def test_status_maps_state(self):
        t = _null(
            responses=[
                b"2\r\n",
                b"0\r\n",
                b"1.1\r\n",
                b"0.3\r\n",
                b"0.2\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        status = m.status
        assert status.state.value == "at_target"
        assert status.at_target is True
        assert status.current == pytest.approx(1.1)
        assert status.field == pytest.approx(0.3)
        assert status.voltage == pytest.approx(0.2)
        assert status.heater_on is False
        assert t.write_log == [b"OPST?\r\n", b"PSH?\r\n", b"RDGI?\r\n", b"RDGF?\r\n", b"RDGV?\r\n"]

    def test_status_maps_ramping_state(self):
        t = _null(
            responses=[
                b"0\r\n",
                b"0.5\r\n",
                b"0.1\r\n",
                b"0.1\r\n",
                b"1\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        status = m.status
        assert status.state.value == "ramping"
        assert status.at_target is False

    def test_status_maps_compliance_as_fault_state(self):
        t = _null(
            responses=[
                b"1\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        status = m.status
        assert status.state.value == "fault"

    def test_status_ignores_psh_stable_bit_for_magnet_state(self):
        t = _null(
            responses=[
                b"6\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        status = m.status
        assert status.state.value == "at_target"

    def test_status_unknown_for_unparseable_rdgst_response(self, caplog):
        t = _null(
            responses=[
                b"not-an-int\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        with caplog.at_level(logging.WARNING, logger="stoner_measurement.sequence.comms"):
            status = m.status
        assert status.state is MagnetState.UNKNOWN
        assert status.at_target is False
        assert any("OPST? returned unexpected response" in record.getMessage() for record in caplog.records)

    def test_status_unknown_for_unhandled_rdgst_bits(self, caplog):
        t = _null(
            responses=[
                b"16\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0.0\r\n",
                b"0\r\n",
            ]
        )
        m = Lakeshore625(transport=t)
        with caplog.at_level(logging.WARNING, logger="stoner_measurement.sequence.comms"):
            status = m.status
        assert status.state is MagnetState.UNKNOWN
        assert status.at_target is False
        assert any("OPST? returned unhandled status bits 0x10" in record.getMessage() for record in caplog.records)

    def test_set_magnet_constant_validation(self):
        m = Lakeshore625(transport=_null())
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(0.0)
        with pytest.raises(ValueError, match="positive"):
            m.set_magnet_constant(-1.0)

    def test_refresh_magnet_constant_reads_flds_query_in_t_per_amp(self):
        t = _null(responses=[b"0,+0.0750\r\n"])
        m = Lakeshore625(transport=t)
        assert m.refresh_magnet_constant() == pytest.approx(0.075)
        assert t.write_log == [b"FLDS?\r\n"]

    def test_magnet_constant_property_returns_cached_value(self):
        m = Lakeshore625(transport=_null())
        m._magnet_constant = 0.075  # noqa: SLF001
        assert m.magnet_constant == pytest.approx(0.075)

    def test_refresh_magnet_constant_converts_flds_query_from_kg_per_amp(self):
        t = _null(responses=[b"1,+0.7500\r\n"])
        m = Lakeshore625(transport=t)
        assert m.refresh_magnet_constant() == pytest.approx(0.075)

    def test_set_magnet_constant_writes_flds_command(self):
        t = _null()
        m = Lakeshore625(transport=t)
        m.set_magnet_constant(0.075)
        assert t.write_log == [b"FLDS 0,0.075\r\n"]

    def test_limits_use_cached_field_constant(self):
        t = _null(responses=[b"+60.1000,+5.0000,+2.0000\r\n"])
        m = Lakeshore625(transport=t)
        m._magnet_constant = 0.1  # noqa: SLF001
        limits = m.limits
        assert limits.max_current == pytest.approx(60.1)
        assert limits.max_field == pytest.approx(6.01)
        assert limits.max_ramp_rate == pytest.approx(12.0)
        assert t.write_log == [b"LIMIT?\r\n"]

    def test_set_limits_writes_limit_command_with_current_ramp_rate(self):
        t = _null(responses=[b"+5.0000\r\n"])
        m = Lakeshore625(transport=t)
        m.set_magnet_constant(0.1)
        m.set_limits(MagnetLimits(max_current=50.0, max_field=5.0, max_ramp_rate=12.0))
        assert t.write_log == [
            b"FLDS 0,0.1\r\n",
            b"SETV?\r\n",
            b"LIMIT 50.0,5.0,2.0\r\n",
        ]

    def test_query_float_raises_for_unparseable_numeric_response(self):
        t = _null(responses=[b"not-a-float\r\n"])
        m = Lakeshore625(transport=t)
        with pytest.raises(ValueError):
            _ = m.current

    def test_wait_for_ramp_raises_timeout_when_stuck_ramping(self, monkeypatch):
        m = Lakeshore625(transport=_null())

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
                message="ramping",
            )

        monkeypatch.setattr(Lakeshore625, "status", property(_always_ramping))
        with pytest.raises(TimeoutError):
            m._wait_for_ramp_complete(timeout=0.01, poll_period=0.0)

    def test_lakeshore525_is_alias_for_lakeshore625(self):
        """Lakeshore525 is a backward-compatibility alias for Lakeshore625."""
        assert Lakeshore525 is Lakeshore625


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
