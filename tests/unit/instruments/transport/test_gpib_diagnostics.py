"""Opt-in timing capture must survive blocked calls without GUI delivery."""

import threading

import pytest

from stoner_measurement.instruments.transport import GpibTransport
from stoner_measurement import telemetry as diagnostics


@pytest.fixture(autouse=True)
def capture_cleanup():
    yield
    diagnostics.stop_capture()


def test_disabled_capture_does_not_read_clock(monkeypatch):
    def unexpected():
        pytest.fail("timing clock used while disabled")

    monkeypatch.setattr(diagnostics, "perf_counter", unexpected)
    assert diagnostics.timed_call("GPIB0::1::INSTR", "one", "test", lambda: 42) == 42


def test_start_is_written_before_blocked_call_returns(tmp_path):
    path = tmp_path / "capture.log"
    diagnostics.start_capture(str(path))
    entered, release = threading.Event(), threading.Event()

    def native_call():
        entered.set()
        assert release.wait(5)

    worker = threading.Thread(target=lambda: diagnostics.timed_call(
        "GPIB0::25::1::INSTR", "attempt-1", "device_clear", native_call,
    ))
    worker.start()
    try:
        assert entered.wait(3)
        text = path.read_text(encoding="utf-8")
        assert "stage=device_clear START" in text
        assert "stage=device_clear END" not in text
    finally:
        release.set()
        worker.join(5)
    assert "stage=device_clear END elapsed_ms=" in path.read_text(encoding="utf-8")


def test_failure_records_elapsed_and_preserves_exception(tmp_path, monkeypatch):
    path = tmp_path / "capture.log"
    diagnostics.start_capture(str(path))
    ticks = iter((10.0, 10.25))
    monkeypatch.setattr(diagnostics, "perf_counter", lambda: next(ticks))
    failure = RuntimeError("device absent")

    def fail():
        raise failure

    with pytest.raises(RuntimeError) as raised:
        diagnostics.timed_call("GPIB0::1::INSTR", "one", "open_resource", fail)
    assert raised.value is failure
    text = path.read_text(encoding="utf-8")
    assert "FAILED elapsed_ms=250.000 exception=RuntimeError message=device absent" in text


def test_gpib_connection_stages_and_swallowed_clear_failure(tmp_path, monkeypatch):
    import pyvisa

    path = tmp_path / "capture.log"
    diagnostics.start_capture(str(path))

    class Resource:
        def clear(self):
            raise pyvisa.VisaIOError(pyvisa.constants.StatusCode.error_timeout)

        def write_raw(self, data):
            assert data == b"*IDN?\n"

        def read_stb(self):
            return 0

        def read_raw(self, count):
            return b"instrument\n"

        def close(self):
            pass

    class Manager:
        def open_resource(self, resource):
            assert resource == "GPIB0::25::1::INSTR"
            return Resource()

    monkeypatch.setattr(pyvisa, "ResourceManager", Manager)
    transport = GpibTransport.from_resource_string("GPIB0::25::1::INSTR", use_mav=False)
    transport.open()
    transport.flush()
    transport.write(b"*IDN?\n")
    assert transport.read() == b"instrument\n"
    transport.close()
    text = path.read_text(encoding="utf-8")
    for stage in ("resource_manager", "open_resource", "set_timeout", "set_send_end",
                  "set_read_termination", "write_raw", "write_serial_poll", "read_raw", "close_resource"):
        assert f"stage={stage} START" in text
        assert f"stage={stage} END elapsed_ms=" in text
    assert "stage=device_clear FAILED" in text
    assert "args=(b'*IDN?\\n',)" in text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
