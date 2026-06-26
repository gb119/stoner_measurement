"""Tests for PyVISA-backed GPIB transports."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.protocol import LakeshoreProtocol, OxfordProtocol


class TestGpibProtocolTermination:
    @staticmethod
    def _make_fake_gpib_resource_manager():
        class _FakeResource:
            def __init__(self):
                self.timeout = None
                self.read_termination = None
                self.send_end = None
                self.trigger_count = 0

            def close(self):
                pass

            def read_stb(self):
                return 0x00

            def write_raw(self, _data):
                pass

            def read_raw(self, _num_bytes=4096):
                return b""

            def assert_trigger(self):
                self.trigger_count += 1

        class _FakeResourceManager:
            def __init__(self, resource):
                self._resource = resource

            def open_resource(self, _resource_string):
                return self._resource

            def close(self):
                pass

        resource = _FakeResource()
        return resource, lambda: _FakeResourceManager(resource)

    def test_gpib_protocol_applied_before_open_configures_resource(self, monkeypatch):
        pytest.importorskip("pyvisa")
        import pyvisa

        from stoner_measurement.instruments.transport import GpibTransport

        resource, rm_factory = self._make_fake_gpib_resource_manager()
        monkeypatch.setattr(pyvisa, "ResourceManager", rm_factory)

        transport = GpibTransport(address=22)
        transport.set_protocol(LakeshoreProtocol())
        transport.open()
        assert resource.read_termination == "\r\n"
        assert resource.send_end is True
        transport.close()

    def test_gpib_protocol_set_after_open_updates_read_termination(self, monkeypatch):
        pytest.importorskip("pyvisa")
        import pyvisa

        from stoner_measurement.instruments.transport import GpibTransport

        resource, rm_factory = self._make_fake_gpib_resource_manager()
        monkeypatch.setattr(pyvisa, "ResourceManager", rm_factory)

        transport = GpibTransport(address=22)
        transport.open()
        transport.set_protocol(OxfordProtocol())
        assert resource.read_termination == "\r"
        assert resource.send_end is True
        transport.close()

    def test_gpib_send_group_execute_trigger(self, monkeypatch):
        pytest.importorskip("pyvisa")
        import pyvisa

        from stoner_measurement.instruments.transport import GpibTransport

        resource, rm_factory = self._make_fake_gpib_resource_manager()
        monkeypatch.setattr(pyvisa, "ResourceManager", rm_factory)

        transport = GpibTransport(address=22)
        transport.open()
        transport.send_group_execute_trigger()
        assert resource.trigger_count == 1
        transport.close()


class TestPassThroughGpibTransport:
    class _FakeResource:
        def __init__(self, responses=None):
            self._responses = list(responses or [])
            self.write_log = []
            self.timeout = None
            self.read_termination = None
            self.send_end = None

        def write_raw(self, data):
            self.write_log.append(data)

        def read_raw(self, _num_bytes=4096):
            if self._responses:
                return self._responses.pop(0)
            return b""

        def read_stb(self):
            return 0x00

    def test_write_wraps_command_for_6221_serial_send(self):
        from stoner_measurement.instruments.transport.gpib_transport import PassThroughGpibTransport

        transport = PassThroughGpibTransport(address=22)
        resource = self._FakeResource(responses=[b"0"])
        transport._resource = resource

        transport.write(b"*IDN?")

        assert resource.write_log == [b'SYST:COMM:SER:SEND "*IDN?;*STB?";ENT?']
        assert transport.last_stb == 0

    def test_read_queries_ent_and_returns_payload_bytes(self):
        from stoner_measurement.instruments.transport.gpib_transport import PassThroughGpibTransport

        transport = PassThroughGpibTransport(address=22)
        resource = self._FakeResource(responses=[b"1.23\r\n\n;0"])
        transport._resource = resource

        value = transport.read()

        assert value == b"1.23\r\n\n"
        assert resource.write_log == [b'SYST:COMM:SER:SEND "*STB?";ENT?']
        assert transport.last_stb == 0

    def test_read_status_byte_returns_cached_last_stb(self):
        from stoner_measurement.instruments.transport.gpib_transport import PassThroughGpibTransport

        transport = PassThroughGpibTransport(address=22)
        resource = self._FakeResource()
        transport._resource = resource
        transport.last_stb = 4

        value = transport.read_status_byte()

        assert value == 4
        assert resource.write_log == []
