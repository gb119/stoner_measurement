"""Hardware-free contract tests for the native FTDI D2XX transport."""

from __future__ import annotations

import ctypes
from collections.abc import Callable

import pytest

from stoner_measurement.instruments.transport.ftdi_d2xx_transport import (
    FtdiD2xxError,
    FtdiD2xxTransport,
)


class _FakeFunction:
    def __init__(self, handler: Callable[..., int]) -> None:
        self.handler = handler
        self.calls: list[tuple] = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.handler(*args)


class _FakeD2xx:
    def __init__(self) -> None:
        self.queue_sizes: list[int] = []
        self.read_chunks: list[bytes] = []
        self.write_count: int | None = None
        self.statuses: dict[str, int] = {}
        self.FT_Open = _FakeFunction(self._open)
        self.FT_OpenEx = _FakeFunction(self._open_ex)
        self.FT_Close = _FakeFunction(lambda _handle: self._status("close"))
        self.FT_Read = _FakeFunction(self._read)
        self.FT_Write = _FakeFunction(self._write)
        self.FT_SetTimeouts = _FakeFunction(
            lambda _handle, _read_ms, _write_ms: self._status("timeouts")
        )
        self.FT_GetQueueStatus = _FakeFunction(self._queue_status)
        self.FT_Purge = _FakeFunction(lambda _handle, _mask: self._status("purge"))

    def _status(self, operation: str) -> int:
        return self.statuses.get(operation, 0)

    def _open(self, _index, handle_pointer) -> int:
        handle_pointer._obj.value = 123  # noqa: SLF001
        return self._status("open")

    def _open_ex(self, _serial, _mode, handle_pointer) -> int:
        handle_pointer._obj.value = 456  # noqa: SLF001
        return self._status("open")

    def _write(self, _handle, _buffer, length, written_pointer) -> int:
        written_pointer._obj.value = (  # noqa: SLF001
            length if self.write_count is None else self.write_count
        )
        return self._status("write")

    def _queue_status(self, _handle, queued_pointer) -> int:
        queued_pointer._obj.value = self.queue_sizes.pop(0) if self.queue_sizes else 0  # noqa: SLF001
        return self._status("queue")

    def _read(self, _handle, buffer, available, received_pointer) -> int:
        chunk = self.read_chunks.pop(0)[:available]
        ctypes.memmove(buffer, chunk, len(chunk))
        received_pointer._obj.value = len(chunk)  # noqa: SLF001
        return self._status("read")


def _transport(
    library: _FakeD2xx, device: int | str = 0, **kwargs
) -> FtdiD2xxTransport:
    transport = FtdiD2xxTransport(device, **kwargs)
    transport._load_library = lambda: library  # type: ignore[method-assign]  # noqa: SLF001
    return transport


@pytest.mark.parametrize(
    ("device", "address"),
    [(0, "FTDI::index:0"), (3, "FTDI::index:3"), ("ABC123", "FTDI::serial:ABC123")],
)
def test_transport_address_describes_selection(device, address):
    assert FtdiD2xxTransport(device).transport_address == address


@pytest.mark.parametrize("device", [2, "ABC123"])
def test_open_configures_index_or_serial_device_and_timeouts(device):
    library = _FakeD2xx()
    transport = _transport(library, device, timeout=0.125, write_timeout=0.75)

    transport.open()
    transport.open()

    assert transport.is_open is True
    assert transport._handle.value in {123, 456}  # noqa: SLF001
    assert len(library.FT_Open.calls) == (0 if isinstance(device, str) else 1)
    assert len(library.FT_OpenEx.calls) == (1 if isinstance(device, str) else 0)
    assert library.FT_SetTimeouts.calls[0][1:] == (125, 750)
    assert library.FT_Read.argtypes is not None


def test_open_closes_device_when_timeout_configuration_fails():
    library = _FakeD2xx()
    library.statuses["timeouts"] = 4
    transport = _transport(library)

    with pytest.raises(FtdiD2xxError, match="set timeouts"):
        transport.open()

    assert transport.is_open is False
    assert len(library.FT_Close.calls) == 1


def test_close_releases_handle_and_is_idempotent():
    library = _FakeD2xx()
    transport = _transport(library)
    transport.open()

    transport.close()
    transport.close()

    assert transport.is_open is False
    assert transport._handle.value is None  # noqa: SLF001
    assert len(library.FT_Close.calls) == 1


def test_write_requires_open_device_and_reports_short_writes():
    library = _FakeD2xx()
    transport = _transport(library)
    with pytest.raises(ConnectionError, match="not open"):
        transport.write(b"abc")

    transport.open()
    library.write_count = 2
    with pytest.raises(FtdiD2xxError, match="short write"):
        transport.write(b"abc")


def test_write_sends_complete_payload_and_honours_slow_delay(monkeypatch):
    library = _FakeD2xx()
    transport = _transport(library)
    transport.open()
    sleeps = []
    monkeypatch.setattr(
        "stoner_measurement.instruments.transport.ftdi_d2xx_transport.time.sleep",
        lambda delay: sleeps.append(delay),
    )

    assert transport.write(b"abc", slow=25) == 0

    assert library.FT_Write.calls[0][2] == 3
    assert sleeps == [0.025]


def test_read_accumulates_available_chunks_to_requested_length(monkeypatch):
    library = _FakeD2xx()
    library.queue_sizes = [2, 0, 3]
    library.read_chunks = [b"ab", b"cde"]
    transport = _transport(library, timeout=1.0)
    transport.open()
    monkeypatch.setattr(
        "stoner_measurement.instruments.transport.ftdi_d2xx_transport.time.sleep",
        lambda _delay: None,
    )

    assert transport.read(5) == b"abcde"
    assert len(library.FT_Read.calls) == 2


def test_read_returns_partial_data_at_timeout(monkeypatch):
    library = _FakeD2xx()
    library.queue_sizes = [2, 0]
    library.read_chunks = [b"ab"]
    transport = _transport(library, timeout=0.1)
    transport.open()
    times = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr(
        "stoner_measurement.instruments.transport.ftdi_d2xx_transport.time.monotonic",
        lambda: next(times),
    )

    assert transport.read(5) == b"ab"


def test_read_raises_timeout_when_no_data_arrives(monkeypatch):
    library = _FakeD2xx()
    library.queue_sizes = [0]
    transport = _transport(library, timeout=0.0)
    transport.open()
    monkeypatch.setattr(
        "stoner_measurement.instruments.transport.ftdi_d2xx_transport.time.monotonic",
        lambda: 1.0,
    )

    with pytest.raises(TimeoutError, match="No data received"):
        transport.read(4)


def test_flush_is_noop_when_closed_and_purges_both_queues_when_open():
    library = _FakeD2xx()
    transport = _transport(library)
    transport.flush()
    transport.open()

    transport.flush()

    assert len(library.FT_Purge.calls) == 1
    assert library.FT_Purge.calls[0][1] == 3


def test_live_timeout_change_updates_native_timeouts():
    library = _FakeD2xx()
    transport = _transport(library, timeout=1.0, write_timeout=2.0)
    transport.open()

    transport.timeout = 0.25

    assert library.FT_SetTimeouts.calls[-1][1:] == (250, 2000)


def test_library_load_error_is_reported_as_optional_dependency(monkeypatch, tmp_path):
    dll = tmp_path / "missing.dll"
    transport = FtdiD2xxTransport(dll_path=dll)
    monkeypatch.setattr(
        "stoner_measurement.instruments.transport.ftdi_d2xx_transport.ctypes.CDLL",
        lambda _target: (_ for _ in ()).throw(OSError("missing")),
    )

    with pytest.raises(ImportError, match="Unable to load"):
        transport._load_library()  # noqa: SLF001


def test_nonzero_d2xx_status_includes_operation_and_status():
    with pytest.raises(FtdiD2xxError, match=r"write.*FT_STATUS=7"):
        FtdiD2xxTransport._check(7, "write")  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
