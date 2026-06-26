"""Tests for transport URI and VISA resource parsing."""

from __future__ import annotations

import pytest


class TestFromUriSchemes:
    """Tests for BaseTransport.from_uri with scheme://... URIs."""

    def test_tcp_uri_returns_ethernet_transport(self):
        from stoner_measurement.instruments.transport import BaseTransport, EthernetTransport

        transport = BaseTransport.from_uri("tcp://192.168.1.100:5025")
        assert isinstance(transport, EthernetTransport)
        assert transport.host == "192.168.1.100"
        assert transport.port == 5025

    def test_tcpip_scheme_alias(self):
        from stoner_measurement.instruments.transport import BaseTransport, EthernetTransport

        transport = BaseTransport.from_uri("tcpip://10.0.0.5:1234")
        assert isinstance(transport, EthernetTransport)
        assert transport.host == "10.0.0.5"
        assert transport.port == 1234

    def test_tcp_uri_custom_timeout(self):
        from stoner_measurement.instruments.transport import BaseTransport

        transport = BaseTransport.from_uri("tcp://192.168.1.100:5025?timeout=5.0")
        assert transport.timeout == 5.0

    def test_tcp_uri_missing_port_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="host and port"):
            BaseTransport.from_uri("tcp://192.168.1.100")

    def test_udp_uri_returns_udp_transport(self):
        from stoner_measurement.instruments.transport import BaseTransport, UdpTransport

        transport = BaseTransport.from_uri("udp://10.0.0.1:8000")
        assert isinstance(transport, UdpTransport)
        assert transport.host == "10.0.0.1"
        assert transport.port == 8000

    def test_udp_uri_custom_timeout(self):
        from stoner_measurement.instruments.transport import BaseTransport

        transport = BaseTransport.from_uri("udp://10.0.0.1:8000?timeout=3.5")
        assert transport.timeout == 3.5

    def test_udp_uri_missing_port_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="host and port"):
            BaseTransport.from_uri("udp://10.0.0.1")

    def test_serial_unix_uri(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import BaseTransport, SerialTransport

        transport = BaseTransport.from_uri("serial:///dev/ttyUSB0?baud_rate=9600")
        assert isinstance(transport, SerialTransport)
        assert transport.port == "/dev/ttyUSB0"
        assert transport.baud_rate == 9600

    def test_serial_windows_uri(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import BaseTransport, SerialTransport

        transport = BaseTransport.from_uri("serial://COM3?baud_rate=115200")
        assert isinstance(transport, SerialTransport)
        assert transport.port == "COM3"
        assert transport.baud_rate == 115200

    def test_serial_uri_baud_alias(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import BaseTransport

        transport = BaseTransport.from_uri("serial:///dev/ttyUSB0?baud=19200")
        assert transport.baud_rate == 19200

    def test_serial_uri_all_params(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import BaseTransport

        transport = BaseTransport.from_uri(
            "serial:///dev/ttyS0?baud_rate=9600&data_bits=7&stop_bits=2&parity=E&timeout=5.0"
        )
        assert transport.data_bits == 7
        assert transport.stop_bits == 2.0
        assert transport.parity == "E"
        assert transport.timeout == 5.0

    def test_serial_uri_missing_port_raises(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="No serial port"):
            BaseTransport.from_uri("serial://?baud_rate=9600")

    def test_gpib_uri_address_only(self):
        pytest.importorskip("pyvisa")
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        transport = BaseTransport.from_uri("gpib://22/")
        assert isinstance(transport, GpibTransport)
        assert transport.address == 22
        assert transport.board == 0

    def test_gpib_uri_board_and_address(self):
        pytest.importorskip("pyvisa")
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        transport = BaseTransport.from_uri("gpib://1:14/")
        assert isinstance(transport, GpibTransport)
        assert transport.board == 1
        assert transport.address == 14

    def test_gpib_uri_custom_timeout(self):
        pytest.importorskip("pyvisa")
        from stoner_measurement.instruments.transport import BaseTransport

        transport = BaseTransport.from_uri("gpib://22/?timeout=10.0")
        assert transport.timeout == 10.0

    def test_unsupported_scheme_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="Unsupported URI scheme"):
            BaseTransport.from_uri("ftp://somehost:21")


class TestFromUriVisaResourceStrings:
    """Tests for BaseTransport.from_uri with VISA resource strings."""

    def test_gpib_visa_returns_gpib_transport(self):
        pytest.importorskip("pyvisa")
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        transport = BaseTransport.from_uri("GPIB0::22::INSTR")
        assert isinstance(transport, GpibTransport)
        assert transport.address == 22
        assert transport.board == 0

    def test_gpib_visa_no_board_defaults_to_zero(self):
        pytest.importorskip("pyvisa")
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        transport = BaseTransport.from_uri("GPIB::14::INSTR")
        assert isinstance(transport, GpibTransport)
        assert transport.address == 14
        assert transport.board == 0

    def test_gpib_visa_nonzero_board(self):
        pytest.importorskip("pyvisa")
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        transport = BaseTransport.from_uri("GPIB1::7::INSTR")
        assert isinstance(transport, GpibTransport)
        assert transport.address == 7
        assert transport.board == 1

    def test_gpib_visa_lowercase(self):
        pytest.importorskip("pyvisa")
        from stoner_measurement.instruments.transport import BaseTransport, GpibTransport

        transport = BaseTransport.from_uri("gpib0::22::instr")
        assert isinstance(transport, GpibTransport)
        assert transport.address == 22

    def test_tcpip_visa_socket_returns_ethernet_transport(self):
        from stoner_measurement.instruments.transport import BaseTransport, EthernetTransport

        transport = BaseTransport.from_uri("TCPIP::192.168.1.100::5025::SOCKET")
        assert isinstance(transport, EthernetTransport)
        assert transport.host == "192.168.1.100"
        assert transport.port == 5025

    def test_tcpip_visa_with_board_number(self):
        from stoner_measurement.instruments.transport import BaseTransport, EthernetTransport

        transport = BaseTransport.from_uri("TCPIP0::10.0.0.5::1234::SOCKET")
        assert isinstance(transport, EthernetTransport)
        assert transport.host == "10.0.0.5"
        assert transport.port == 1234

    def test_tcpip_visa_instr_uses_default_port(self):
        from stoner_measurement.instruments.transport import BaseTransport, EthernetTransport

        transport = BaseTransport.from_uri("TCPIP::192.168.1.100::INSTR")
        assert isinstance(transport, EthernetTransport)
        assert transport.host == "192.168.1.100"
        assert transport.port == 5025

    def test_asrl_unix_device(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import BaseTransport, SerialTransport

        transport = BaseTransport.from_uri("ASRL/dev/ttyUSB0::INSTR")
        assert isinstance(transport, SerialTransport)
        assert transport.port == "/dev/ttyUSB0"

    def test_asrl_windows_com_port(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import BaseTransport, SerialTransport

        transport = BaseTransport.from_uri("ASRLCOM3::INSTR")
        assert isinstance(transport, SerialTransport)
        assert transport.port == "COM3"

    def test_asrl_lowercase(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import BaseTransport, SerialTransport

        transport = BaseTransport.from_uri("asrl/dev/ttyS0::INSTR")
        assert isinstance(transport, SerialTransport)
        assert transport.port == "/dev/ttyS0"

    def test_asrl_empty_port_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="No serial port"):
            BaseTransport.from_uri("ASRL::INSTR")

    def test_unrecognised_visa_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="Unrecognised VISA resource string"):
            BaseTransport.from_uri("USB0::0x1234::0x5678::SN001::INSTR")

    def test_plain_string_without_scheme_raises(self):
        from stoner_measurement.instruments.transport import BaseTransport

        with pytest.raises(ValueError, match="Unrecognised VISA resource string"):
            BaseTransport.from_uri("notauri")
