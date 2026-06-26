"""Tests for the serial-port transport."""

from __future__ import annotations

import pytest


class TestSerialTransportFlowControl:
    """Tests for the flow-control parameters on SerialTransport."""

    def test_default_xonxoff_is_false(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import SerialTransport

        assert SerialTransport(port="/dev/ttyUSB0").xonxoff is False

    def test_default_rtscts_is_false(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import SerialTransport

        assert SerialTransport(port="/dev/ttyUSB0").rtscts is False

    def test_xonxoff_can_be_enabled(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import SerialTransport

        assert SerialTransport(port="/dev/ttyUSB0", xonxoff=True).xonxoff is True

    def test_rtscts_can_be_enabled(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import SerialTransport

        assert SerialTransport(port="/dev/ttyUSB0", rtscts=True).rtscts is True

    def test_serial_uri_xonxoff_true(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import BaseTransport

        transport = BaseTransport.from_uri("serial:///dev/ttyUSB0?xonxoff=true")
        assert transport.xonxoff is True
        assert transport.rtscts is False

    def test_serial_uri_rtscts_true(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import BaseTransport

        transport = BaseTransport.from_uri("serial:///dev/ttyUSB0?rtscts=1")
        assert transport.rtscts is True
        assert transport.xonxoff is False

    def test_serial_uri_no_flow_control_by_default(self):
        pytest.importorskip("serial")
        from stoner_measurement.instruments.transport import BaseTransport

        transport = BaseTransport.from_uri("serial:///dev/ttyUSB0")
        assert transport.xonxoff is False
        assert transport.rtscts is False
