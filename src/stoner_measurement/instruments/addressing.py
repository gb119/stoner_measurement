"""Helpers for parsing instrument transport address strings.

This module centralises parsing logic for the custom address-string formats
used by controller engines when constructing transport objects.
"""

from __future__ import annotations

DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_SERIAL_BAUD = 9600
DEFAULT_ETHERNET_HOST = "localhost"
DEFAULT_ETHERNET_PORT = 5025


def parse_serial_address(address: str) -> tuple[str, int]:
    """Parse a serial address string in ``port=<device>;baud=<rate>`` format.

    Missing values default to ``"/dev/ttyUSB0"`` for the port and ``9600`` for
    the baud rate.

    Args:
        address (str):
            Serial address string (for example
            ``"port=/dev/ttyUSB0;baud=9600"``).

    Returns:
        (tuple[str, int]):
            Parsed ``(port, baud_rate)`` tuple.

    Raises:
        ValueError:
            If a baud value is supplied but cannot be parsed as an integer.
    """
    port = DEFAULT_SERIAL_PORT
    baud = DEFAULT_SERIAL_BAUD
    for part in (p.strip() for p in address.split(";") if p.strip()):
        key, sep, value = part.partition("=")
        if sep != "=":
            continue
        key = key.strip().lower()
        if key == "port" and value.strip():
            port = value.strip()
        elif key == "baud":
            raw_baud = value.strip()
            try:
                baud = int(raw_baud)
            except ValueError as exc:
                raise ValueError(
                    "Invalid serial baud in address "
                    f"{address!r}: {raw_baud!r}. Expected format "
                    "'port=<device>;baud=<rate>'."
                ) from exc
    return port, baud


def parse_ethernet_address(address: str) -> tuple[str, int]:
    """Parse an Ethernet address string in ``<host>:<port>`` format.

    Empty values default to ``"localhost"`` and ``5025``. If only a host is
    provided, the default port is used.

    Args:
        address (str):
            Ethernet address string (for example ``"localhost:5025"``).

    Returns:
        (tuple[str, int]):
            Parsed ``(host, port)`` tuple.

    Raises:
        ValueError:
            If a port is supplied but is not a valid integer.
    """
    host = DEFAULT_ETHERNET_HOST
    port = DEFAULT_ETHERNET_PORT
    raw = address.strip()
    if not raw:
        return host, port

    parsed_host, sep, parsed_port = raw.rpartition(":")
    if not sep:
        if raw.isdigit():
            return host, int(raw)
        return raw, port

    parsed_host = parsed_host.strip()
    parsed_port = parsed_port.strip()

    if not parsed_port:
        return (parsed_host or host), port

    try:
        parsed_port_value = int(parsed_port)
    except ValueError as exc:
        raise ValueError(
            "Invalid Ethernet port in address "
            f"{address!r}: {parsed_port!r}. Expected format "
            "'<host>:<port>'."
        ) from exc

    return (parsed_host or host), parsed_port_value
