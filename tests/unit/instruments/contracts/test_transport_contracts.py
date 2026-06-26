"""Shared transport contract tests."""

from __future__ import annotations

from collections.abc import Callable

from stoner_measurement.instruments.transport import BaseTransport, NullTransport


TransportFactory = Callable[[list[bytes] | None], BaseTransport]


def assert_open_close_contract(make_transport: TransportFactory) -> None:
    """Assert the common open/close state contract for a transport."""
    transport = make_transport(None)
    assert not transport.is_open

    transport.open()
    assert transport.is_open

    transport.close()
    assert not transport.is_open


def assert_context_manager_contract(make_transport: TransportFactory) -> None:
    """Assert the common context-manager lifecycle contract."""
    with make_transport(None) as transport:
        assert transport.is_open

    assert not transport.is_open


def assert_query_contract(make_transport: TransportFactory) -> None:
    """Assert query writes the command before reading the response."""
    transport = make_transport([b"answer\n"])
    transport.open()

    assert transport.query(b"*IDN?\n") == b"answer\n"
    assert getattr(transport, "write_log") == [b"*IDN?\n"]


def _null_transport_factory(responses: list[bytes] | None = None) -> BaseTransport:
    return NullTransport(responses=responses)


def test_null_transport_satisfies_open_close_contract():
    assert_open_close_contract(_null_transport_factory)


def test_null_transport_satisfies_context_manager_contract():
    assert_context_manager_contract(_null_transport_factory)


def test_null_transport_satisfies_query_contract():
    assert_query_contract(_null_transport_factory)
