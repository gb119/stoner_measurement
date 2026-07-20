"""Focused tests for the MKS mass-flow-controller drivers."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments import MassFlowController, MassFlowControllerCapabilities
from stoner_measurement.instruments.mks import MKSPR4000BS, MKSPSR1A, MKSPSR4A
from stoner_measurement.instruments.protocol import MKSPR4000Protocol, MKSPSRProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestMKSPR4000BS:
    def test_default_protocol_is_pr4000(self):
        controller = MKSPR4000BS(transport=NullTransport())
        assert isinstance(controller.protocol, MKSPR4000Protocol)
        assert isinstance(controller, MassFlowController)

    def test_capabilities(self):
        caps = MKSPR4000BS(transport=NullTransport()).get_capabilities()
        assert caps == MassFlowControllerCapabilities(
            channel_count=1,
            supports_unit_control=True,
            supports_range_control=True,
            supports_valve_control=True,
            supports_pressure_control=True,
            supports_batch=False,
            supports_blend=False,
        )

    def test_read_actual_value(self):
        transport = _null(responses=[b"+1.2345\r"])
        controller = MKSPR4000BS(transport=transport)
        assert controller.read_actual_value() == pytest.approx(1.2345)
        assert transport.write_log == [b"$\r"]

    def test_read_setpoint(self):
        transport = _null(responses=[b"+2.5000\r"])
        controller = MKSPR4000BS(transport=transport)
        assert controller.read_setpoint() == pytest.approx(2.5)
        assert transport.write_log == [b"`\r"]

    def test_set_setpoint_uses_query_style_ack(self):
        transport = _null(responses=[b"\r"])
        controller = MKSPR4000BS(transport=transport)
        controller.set_setpoint(1.25)
        assert transport.write_log == [b"@+1.25000\r"]

    def test_unit_range_and_valve_methods(self):
        transport = _null(
            responses=[
                b"012\r",
                b"\r",
                b"+100.000\r",
                b"\r",
                b"001\r",
                b"\r",
            ]
        )
        controller = MKSPR4000BS(transport=transport)
        assert controller.read_unit() == 12
        controller.set_unit(12)
        assert controller.read_range() == pytest.approx(100.0)
        controller.set_range(100.0)
        assert controller.valve_enabled() is True
        controller.set_valve_enabled(False)
        assert transport.write_log == [
            b"c\r",
            b"C012\r",
            b"b\r",
            b"B+100.00000\r",
            b"a\r",
            b"A000\r",
        ]

    def test_read_status_bytes(self):
        transport = _null(responses=[b"001\r", b"002\r", b"003\r", b"004\r"])
        controller = MKSPR4000BS(transport=transport)
        assert controller.read_status_bytes() == (1, 2, 3, 4)

    def test_validate_single_channel(self):
        controller = MKSPR4000BS(transport=NullTransport())
        with pytest.raises(ValueError, match="supports channels 1..1"):
            controller.read_actual_value(channel=2)


class TestMKSPSRFamily:
    def test_default_protocol_is_psr(self):
        controller = MKSPSR1A(transport=NullTransport())
        assert isinstance(controller.protocol, MKSPSRProtocol)
        assert isinstance(controller, MassFlowController)

    def test_psr_identity_parser_extracts_model(self):
        parsed = MKSPSR1A.parse_identity_response(
            "AZ, 32596,4,MKS Instruments, Model PSR1A,02,21.09.03,EE00,5C"
        )
        assert parsed["network_address"] == "32596"
        assert parsed["manufacturer"] == "MKS Instruments"
        assert parsed["model"] == "PSR1A"
        assert parsed["firmware_version"] == "21.09.03"

    def test_psr1a_capabilities(self):
        caps = MKSPSR1A(transport=NullTransport()).get_capabilities()
        assert caps.channel_count == 1
        assert caps.supports_batch is True
        assert caps.supports_blend is False

    def test_psr4a_capabilities(self):
        caps = MKSPSR4A(transport=NullTransport()).get_capabilities()
        assert caps.channel_count == 4
        assert caps.supports_batch is True
        assert caps.supports_blend is True

    def test_read_actual_value_uses_measured_channel_command(self):
        transport = _null(responses=[b"AZ,12345.01,4,K,+12.50,8F\r\n"])
        controller = MKSPSR1A(transport=transport)
        assert controller.read_actual_value() == pytest.approx(12.5)
        assert transport.write_log == [b"AZ.01K\r"]

    def test_read_and_write_setpoint(self):
        transport = _null(
            responses=[
                b"AZ,12345.02,4,P01,125,8F\r\n",
                b"AZ,12345.02,4,P01,250,90\r\n",
            ]
        )
        controller = MKSPSR1A(transport=transport)
        assert controller.read_setpoint() == pytest.approx(1.25)
        controller.set_setpoint(2.5)
        assert transport.write_log == [b"AZ.02P01\r", b"AZ.02P01=250\r"]

    def test_read_and_write_range_and_unit(self):
        transport = _null(
            responses=[
                b"AZ,12345.01,4,P04,18,80\r\n",
                b"AZ,12345.01,4,P04,24,84\r\n",
                b"AZ,12345.01,4,P09,10000,8A\r\n",
                b"AZ,12345.01,4,P09,5000,82\r\n",
                b"AZ,12345.02,4,P09,5000,82\r\n",
            ]
        )
        controller = MKSPSR1A(transport=transport)
        assert controller.read_unit() == 18
        controller.set_unit(24)
        assert controller.read_range() == pytest.approx(100.0)
        controller.set_range(50.0)
        assert transport.write_log == [
            b"AZ.01P04\r",
            b"AZ.01P04=24\r",
            b"AZ.01P09\r",
            b"AZ.01P09=5000\r",
            b"AZ.02P09=5000\r",
        ]

    def test_psr4a_channel_mapping(self):
        transport = _null(responses=[b"AZ,12345.07,4,K,+3.00,8F\r\n"])
        controller = MKSPSR4A(transport=transport)
        assert controller.read_actual_value(channel=4) == pytest.approx(3.0)
        assert transport.write_log == [b"AZ.07K\r"]

    def test_configure_mfc_channel_writes_expected_parameter_indices(self):
        transport = _null(
            responses=[
                b"AZ,12345.01,4,P00,;,70\r\n",
                b"AZ,12345.01,4,P04,18,80\r\n",
                b"AZ,12345.01,4,P09,10000,8A\r\n",
                b"AZ,12345.01,4,P10,2,72\r\n",
                b"AZ,12345.02,4,P00,5,75\r\n",
                b"AZ,12345.02,4,P02,1,71\r\n",
                b"AZ,12345.02,4,P09,10000,8A\r\n",
                b"AZ,12345.02,4,P29,0,79\r\n",
            ]
        )
        controller = MKSPSR1A(transport=transport)
        controller.configure_mfc_channel(channel=1, full_scale=100.0)
        assert transport.write_log == [
            b"AZ.01P00=;\r",
            b"AZ.01P04=18\r",
            b"AZ.01P09=10000\r",
            b"AZ.01P10=2\r",
            b"AZ.02P00=5\r",
            b"AZ.02P02=1\r",
            b"AZ.02P09=10000\r",
            b"AZ.02P29=0\r",
        ]

    def test_validate_channel_rejects_out_of_range(self):
        controller = MKSPSR4A(transport=NullTransport())
        with pytest.raises(ValueError, match="supports channels 1..4"):
            controller.read_setpoint(channel=5)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
