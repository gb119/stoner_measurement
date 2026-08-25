"""Tests for shared IEEE 488.2 binary-block framing."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.protocol import ScpiProtocol, parse_ieee_block
from stoner_measurement.instruments.transport import NullTransport


def _instrument(responses):
    transport = NullTransport(responses=list(responses))
    transport.open()
    return BaseInstrument(
        transport=transport,
        protocol=ScpiProtocol(),
        auto_check_errors=False,
    )


def test_parse_definite_and_keithley_indefinite_blocks():
    assert parse_ieee_block(b"#14data\n") == b"data"
    assert (
        parse_ieee_block(
            b"#0\x00\x00\x80?\n",
            allow_indefinite=True,
            itemsize=4,
        )
        == b"\x00\x00\x80?"
    )


def test_query_ieee_block_accumulates_fragmented_response():
    instrument = _instrument([b"#", b"2", b"08", b"ab\ncd", b"efg", b"\n"])

    assert instrument.query_ieee_block(":CALC:DATA?") == b"ab\ncdefg"
    assert instrument.transport.write_log == [b":CALC:DATA?\n"]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (b"data\n", "start"),
        (b"#0data\n", "definite"),
        (b"#2x4data\n", "non-numeric"),
        (b"#14dat\n", "Incomplete"),
        (b"#14dataX\n", "terminator"),
        (b"#14data\nX", "trailing"),
    ],
)
def test_query_ieee_block_rejects_malformed_frames(response, message):
    instrument = _instrument([response])

    with pytest.raises((ValueError, TimeoutError), match=message):
        instrument.query_ieee_block(":CALC:DATA?")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
