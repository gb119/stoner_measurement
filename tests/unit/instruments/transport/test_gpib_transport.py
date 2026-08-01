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

    def test_read_times_out_when_mav_never_appears(self, monkeypatch):
        pytest.importorskip("pyvisa")
        import pyvisa

        from stoner_measurement.instruments.transport import GpibTransport

        resource, rm_factory = self._make_fake_gpib_resource_manager()
        resource.read_stb = lambda: 11
        monkeypatch.setattr(pyvisa, "ResourceManager", rm_factory)
        transport = GpibTransport(address=8, timeout=0.0, command_complete_mask=2)
        transport.open()

        with pytest.raises(TimeoutError, match=r"MAV.*STB=11"):
            transport.read()

        transport.close()

    def test_read_does_not_consume_timeout_while_command_is_executing(self, monkeypatch):
        pytest.importorskip("pyvisa")
        import pyvisa

        import stoner_measurement.instruments.transport.gpib_transport as gpib_module
        from stoner_measurement.instruments.transport import GpibTransport

        resource, rm_factory = self._make_fake_gpib_resource_manager()
        statuses = iter((0, 0, 18, 18, 0))
        resource.read_stb = lambda: next(statuses)
        resource.read_raw = lambda _num_bytes=4096: b"done\n"
        monkeypatch.setattr(pyvisa, "ResourceManager", rm_factory)
        times = iter((0.0, 100.0, 100.0, 200.0, 200.0, 200.0))
        monkeypatch.setattr(gpib_module, "perf_counter", lambda: next(times))
        monkeypatch.setattr(gpib_module, "sleep", lambda _seconds: None)
        transport = GpibTransport(address=8, timeout=1.0, command_complete_mask=2)
        transport.open()

        assert transport.read() == b"done\n"

        transport.close()

    def test_command_complete_status_is_opt_in(self):
        from stoner_measurement.instruments.transport import GpibTransport

        transport = GpibTransport(address=22)

        assert transport._command_complete_mask is None

    def test_close_leaves_shared_resource_manager_and_other_resources_open(self, monkeypatch):
        pytest.importorskip("pyvisa")
        import pyvisa

        from stoner_measurement.instruments.transport import GpibTransport

        class _FakeResource:
            def __init__(self):
                self.closed = False
                self.timeout = None
                self.read_termination = None
                self.send_end = None

            def close(self):
                self.closed = True

        class _SharedResourceManager:
            def __init__(self):
                self.resources = {}
                self.close_calls = 0

            def open_resource(self, resource_string):
                return self.resources.setdefault(resource_string, _FakeResource())

            def close(self):
                self.close_calls += 1
                for resource in self.resources.values():
                    resource.close()

        manager = _SharedResourceManager()
        monkeypatch.setattr(pyvisa, "ResourceManager", lambda: manager)
        first = GpibTransport(address=22)
        second = GpibTransport(address=2)
        first.open()
        second.open()

        first.close()

        assert manager.close_calls == 0
        assert manager.resources["GPIB0::22::INSTR"].closed is True
        assert manager.resources["GPIB0::2::INSTR"].closed is False
        assert second.is_open is True
        second.close()


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
