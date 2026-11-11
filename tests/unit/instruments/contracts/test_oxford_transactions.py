"""Shared Oxford transaction behaviour exercised through both legacy drivers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.oxford import OxfordIPS120, OxfordITC503
from stoner_measurement.instruments.protocol import OxfordProtocol
from stoner_measurement.instruments.transport import NullTransport


@pytest.fixture(params=[OxfordITC503, OxfordIPS120])
def oxford(request):
    """Return either driver with an open, explicitly scripted transport."""
    transport = NullTransport()
    transport.open()
    return request.param(transport)


def test_write_consumes_ack_before_numeric_query(oxford):
    oxford.transport.queue_response(b"T\r")
    oxford.transport.queue_response(b"R12.5\r")
    oxford.write("T12.5")
    assert oxford._query_float("R0") == 12.5
    assert oxford.transport.write_log == [b"T12.5\r", b"R0\r"]


@pytest.mark.parametrize("reply", [b"?T12.5\r", b"A\r", b"T12.5\r", b"TT\r", b"\r"])
@pytest.mark.parametrize("auto_check", [False, True])
def test_invalid_ack_is_rejected_without_repeating_action(oxford, reply, auto_check):
    oxford.auto_check_errors = auto_check
    oxford.transport.queue_response(reply)
    with pytest.raises(InstrumentError) as error:
        oxford.write("T12.5")
    assert error.value.command == "T12.5"
    assert oxford.transport.write_log == [b"T12.5\r"]


@pytest.mark.parametrize("command", ["Q0", "Q2", "Q4", "Q6", "$T12.5"])
def test_reply_free_write_does_not_consume_next_query_reply(oxford, command):
    oxford.transport.queue_response(b"R12.5\r")
    oxford.write(command)
    assert oxford._query_float("R0") == 12.5
    assert oxford.transport.write_log == [command.encode() + b"\r", b"R0\r"]


@pytest.mark.parametrize(
    "command,reply,value",
    [("R0", b"R-1.25\r", -1.25), ("q", b"Q1.25\r", 1.25),
     ("q", b"q2.5,unused\r", 2.5), ("R0", b"3.5\r", 3.5)],
)
def test_shared_numeric_parsing(oxford, command, reply, value):
    oxford.transport.queue_response(reply)
    assert oxford._query_float(command) == value


@pytest.mark.parametrize("reply", [b"Q12.5\r", b"Rgarbage\r", b"R\r", b"\r"])
def test_numeric_query_rejects_wrong_echo_and_malformed_payload(oxford, reply):
    oxford.transport.queue_response(reply)
    with pytest.raises(ValueError, match="Invalid numeric response for R0"):
        oxford._query_float("R0")


def test_write_timeout_propagates_without_retry_and_forwards_delay():
    class TimingTransport(NullTransport):
        def write(self, data, slow=None):
            self.delay = slow
            return super().write(data, slow=slow)

        def read(self, num_bytes=None):
            raise TimeoutError("acknowledgement timed out")

    transport = TimingTransport()
    transport.open()
    instrument = BaseInstrument(transport, OxfordProtocol())
    with pytest.raises(TimeoutError, match="acknowledgement timed out"):
        instrument.write("T12.5", slow=50)
    assert transport.delay == 50
    assert transport.write_log == [b"T12.5\r"]


def test_write_holds_lock_until_acknowledgement_is_validated():
    validating, release = Event(), Event()

    class BlockingProtocol(OxfordProtocol):
        def validate_acknowledgement(self, response, *, command):
            validating.set()
            assert release.wait(2), "Acknowledgement validation was not released"
            super().validate_acknowledgement(response, command=command)

    transport = NullTransport(responses=[b"T\r"])
    transport.open()
    instrument = BaseInstrument(transport, BlockingProtocol())
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(instrument.write, "T12.5")
        try:
            assert validating.wait(2), "Action never reached acknowledgement validation"
            acquired = instrument._lock.acquire(blocking=False)
            if acquired:
                instrument._lock.release()
            assert not acquired, "Another transaction could interrupt acknowledgement validation"
        finally:
            release.set()
        future.result(timeout=2)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
