"""Concurrency contracts for coordinated controller reads."""

import threading

import pytest

from stoner_measurement.core.controller_polling import ControllerPoller, coordinated_read


@pytest.mark.parametrize("result", [None, "fresh snapshot"])
def test_overlapping_reads_share_success_or_failure_and_next_read_is_fresh(result):
    entered = threading.Event()
    overlapping = threading.Event()
    release = threading.Event()

    class Lock:
        def __init__(self):
            self.lock = threading.RLock()

        def __enter__(self):
            if threading.current_thread().name == "overlapping-read":
                overlapping.set()
            self.lock.acquire()

        def __exit__(self, *args):
            self.lock.release()

    class Engine:
        def __init__(self):
            self._engine_lock = Lock()
            self._controller_poller = ControllerPoller()
            self.reads = 0

        @coordinated_read
        def read(self):
            self.reads += 1
            entered.set()
            assert release.wait(2)
            return result

    engine = Engine()
    results = []
    first = threading.Thread(target=lambda: results.append(engine.read()))
    second = threading.Thread(target=lambda: results.append(engine.read()), name="overlapping-read")
    first.start()
    assert entered.wait(1)
    second.start()
    try:
        assert overlapping.wait(1)
    finally:
        release.set()
        first.join(2)
        second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert results == [result, result]
    assert engine.reads == 1
    # A later command must read again, even with a previous successful result.
    assert engine.read() == result
    assert engine.reads == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
