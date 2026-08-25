"""IEEE 488.2 binary-block framing helpers shared by instrument drivers."""

from __future__ import annotations


def parse_ieee_block(
    response: bytes,
    *,
    terminator: bytes = b"\n",
    allow_indefinite: bool = False,
    itemsize: int | None = None,
) -> bytes:
    """Return the payload from a complete IEEE 488.2 binary-block response.

    Definite blocks use ``#<n><length><payload>``. Some Keithley instruments
    instead use the ``#0<payload><terminator>`` indefinite form; callers must
    opt into that form and should provide *itemsize* so a missing terminator
    cannot be confused with a valid final data byte.
    """
    if len(response) < 2 or response[0:1] != b"#":
        raise ValueError("IEEE 488.2 block must start with '#'.")
    digit_token = response[1]
    if digit_token < ord("0") or digit_token > ord("9"):
        raise ValueError("IEEE 488.2 block has an invalid length-digit token.")
    length_digits = digit_token - ord("0")

    if length_digits == 0:
        if not allow_indefinite:
            raise ValueError("Indefinite IEEE 488.2 blocks are not allowed here.")
        payload = response[2:]
        if itemsize is not None and itemsize <= 0:
            raise ValueError("itemsize must be positive.")
        if itemsize is not None and len(payload) % itemsize == 0:
            return payload
        if terminator and payload.endswith(terminator):
            payload = payload[: -len(terminator)]
        if itemsize is not None and len(payload) % itemsize:
            raise ValueError(
                f"Binary payload has {len(payload)} bytes, which is not a whole "
                f"number of {itemsize}-byte values."
            )
        return payload

    header_end = 2 + length_digits
    if len(response) < header_end:
        raise ValueError("IEEE 488.2 block has a truncated length field.")
    length_field = response[2:header_end]
    if not length_field.isdigit():
        raise ValueError("IEEE 488.2 block has a non-numeric length field.")
    payload_length = int(length_field)
    payload_end = header_end + payload_length
    if len(response) < payload_end:
        raise ValueError("IEEE 488.2 block payload is truncated.")
    trailing = response[payload_end:]
    if trailing not in {b"", terminator}:
        raise ValueError("Unexpected trailing data after IEEE 488.2 block response.")
    payload = response[header_end:payload_end]
    if itemsize is not None and len(payload) % itemsize:
        raise ValueError(
            f"Binary payload has {len(payload)} bytes, which is not a whole "
            f"number of {itemsize}-byte values."
        )
    return payload
