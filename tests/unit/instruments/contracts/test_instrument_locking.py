"""Focused tests for BaseInstrument locking and lock-key behavior."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.lock_registry import canonical_resource_key
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport
from stoner_measurement.instruments.transport.gpib_transport import (
    GpibTransport,
    PassThroughGpibTransport,
)


class TestInstrumentLocking:
    """Tests for the RLock serialization of write/query/check_for_errors."""

    class _KeyedTransport(NullTransport):
        """Test helper transport exposing a configurable transport address."""

        def __init__(self, address: str):
            super().__init__()
            self._address = address

        @property
        def transport_address(self) -> str:
            return self._address

    def test_instrument_has_rlock(self):
        import threading

        instrument = BaseInstrument(NullTransport(), ScpiProtocol())
        assert isinstance(instrument._lock, type(threading.RLock()))

    def test_same_resource_key_shares_lock_object(self):
        first = BaseInstrument(self._KeyedTransport(" gpib0::22::instr "), ScpiProtocol())
        second = BaseInstrument(self._KeyedTransport("GPIB0::22::INSTR"), ScpiProtocol())

        assert first._lock is second._lock

    def test_canonical_resource_key_normalises_case_and_whitespace(self):
        assert canonical_resource_key(" gpib0::22::instr ") == "gpib0::22::instr"
        assert canonical_resource_key("  ") is None
        assert canonical_resource_key("\t\r\n") is None
        assert canonical_resource_key("\nGpIb0::22::InStR\t") == "gpib0::22::instr"
        assert canonical_resource_key(None) is None

    def test_different_resource_keys_get_different_locks(self):
        first = BaseInstrument(self._KeyedTransport("GPIB0::22::INSTR"), ScpiProtocol())
        second = BaseInstrument(self._KeyedTransport("GPIB0::23::INSTR"), ScpiProtocol())

        assert first._lock is not second._lock

    def test_unkeyed_transports_keep_per_instance_lock(self):
        first = BaseInstrument(NullTransport(), ScpiProtocol())
        second = BaseInstrument(NullTransport(), ScpiProtocol())

        assert first._lock is not second._lock

    def test_gpib_and_passthrough_transports_share_lock_key(self):
        pytest.importorskip("pyvisa")
        host_transport = GpibTransport(address=22)
        relay_transport = PassThroughGpibTransport(address=22)

        assert host_transport.lock_key == relay_transport.lock_key

        host_instr = BaseInstrument(host_transport, ScpiProtocol())
        relay_instr = BaseInstrument(relay_transport, ScpiProtocol())

        assert host_instr._lock is relay_instr._lock

    def test_connect_flushes_transport(self):
        class _FlushCountingTransport(NullTransport):
            def __init__(self):
                super().__init__()
                self.flush_count = 0

            def flush(self) -> None:
                self.flush_count += 1

        transport = _FlushCountingTransport()
        instrument = BaseInstrument(transport, ScpiProtocol())
        instrument.connect()
        assert transport.flush_count == 1

    def test_query_holds_lock_during_write_read(self):
        import threading

        lock_was_held = []
        barrier = threading.Barrier(2, timeout=2)

        class _BarrierTransport(NullTransport):
            def read(self, num_bytes: int | None = None) -> bytes:
                barrier.wait()
                barrier.wait()
                return b"response\n"

        transport = _BarrierTransport()
        transport.open()
        instrument = BaseInstrument(transport, ScpiProtocol(), auto_check_errors=False)

        def do_query():
            instrument.query("CMD")

        thread = threading.Thread(target=do_query, daemon=True)
        thread.start()
        barrier.wait()
        acquired = instrument._lock.acquire(blocking=False)
        if acquired:
            instrument._lock.release()
        lock_was_held.append(not acquired)
        barrier.wait()
        thread.join(timeout=2)
        assert not thread.is_alive(), "query() worker thread did not finish; possible deadlock"
        assert lock_was_held == [True], "Lock should be held by query thread during read()"

    def test_concurrent_queries_do_not_interleave(self):
        import threading

        events: list[str] = []
        events_lock = threading.Lock()

        class _LoggingTransport(NullTransport):
            def write(self, data: bytes, slow: int | None = None) -> None:
                super().write(data)
                with events_lock:
                    events.append(f"W:{data.strip().decode()}")

            def read(self, num_bytes: int | None = None) -> bytes:
                import time

                time.sleep(0.005)
                last_write = self.write_log[-1].strip().decode() if self.write_log else "?"
                with events_lock:
                    events.append(f"R:{last_write}")
                return f"{last_write}-resp\n".encode()

        transport = _LoggingTransport()
        transport.open()
        instrument = BaseInstrument(transport, ScpiProtocol(), auto_check_errors=False)

        results = []

        def do_query(cmd):
            results.append(instrument.query(cmd))

        thread_1 = threading.Thread(target=do_query, args=("A",), daemon=True)
        thread_2 = threading.Thread(target=do_query, args=("B",), daemon=True)
        thread_1.start()
        thread_2.start()
        thread_1.join(timeout=2)
        thread_2.join(timeout=2)
        assert not thread_1.is_alive(), "First query thread did not finish; possible deadlock"
        assert not thread_2.is_alive(), "Second query thread did not finish; possible deadlock"

        for index in range(0, len(events) - 1, 2):
            write_cmd = events[index][2:]
            read_cmd = events[index + 1][2:]
            assert write_cmd == read_cmd, f"Write {write_cmd!r} was not paired with its read; got {read_cmd!r}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
