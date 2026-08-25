"""Shared data-transfer support for SCPI-speaking Keithley instruments."""

from __future__ import annotations

import sys
from enum import Enum
from typing import cast

import numpy as np

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.electrometer import ElectrometerDataFormat
from stoner_measurement.instruments.protocol.ieee488 import parse_ieee_block

KeithleyDataFormat = ElectrometerDataFormat


class KeithleyByteOrder(Enum):
    """Byte order used for Keithley IEEE-754 response data."""

    NORMAL = "NORM"
    SWAPPED = "SWAP"

    @classmethod
    def native(cls) -> KeithleyByteOrder:
        """Return the instrument byte order matching this Python host."""
        return cls.SWAPPED if sys.byteorder == "little" else cls.NORMAL


class KeithleyScpiDataFormatMixin:
    """Cache and parse the common Keithley ``FORMat`` subsystem state.

    The mixin deliberately caches requested settings.  This avoids format and
    byte-order queries on every bulk transfer while still allowing a driver to
    select a NumPy dtype that views the returned bytes directly.
    """

    _data_format: ElectrometerDataFormat
    _byte_order: KeithleyByteOrder
    _supported_data_formats = tuple(ElectrometerDataFormat)

    def _initialise_data_format_state(self) -> None:
        """Initialise cached state to the IEEE-488.2 reset defaults."""
        self._data_format = ElectrometerDataFormat.ASCII
        self._byte_order = KeithleyByteOrder.NORMAL

    def get_data_format(self) -> ElectrometerDataFormat:
        """Return the cached response data format without querying the instrument."""
        return self._data_format

    def set_data_format(self, data_format: ElectrometerDataFormat) -> None:
        """Set and cache the response data format."""
        if not isinstance(data_format, ElectrometerDataFormat):
            raise TypeError("data_format must be an ElectrometerDataFormat value.")
        if data_format not in self._supported_data_formats:
            supported = ", ".join(item.name for item in self._supported_data_formats)
            raise ValueError(f"Unsupported data format {data_format.name}; choose from {supported}.")
        if data_format is self._data_format:
            return
        cast(BaseInstrument, self).write(f":FORM:DATA {data_format.value}")
        self._data_format = data_format

    def get_byte_order(self) -> KeithleyByteOrder:
        """Return the cached binary byte order without querying the instrument."""
        return self._byte_order

    def set_byte_order(self, byte_order: KeithleyByteOrder) -> None:
        """Set and cache the byte order used for binary response data."""
        if not isinstance(byte_order, KeithleyByteOrder):
            raise TypeError("byte_order must be a KeithleyByteOrder value.")
        if byte_order is self._byte_order:
            return
        cast(BaseInstrument, self).write(f":FORM:BORD {byte_order.value}")
        self._byte_order = byte_order

    def _query_raw(self, command: str, *, slow: int | None = None) -> bytes:
        """Execute a query without decoding its response as text."""
        instrument = cast(BaseInstrument, self)
        with instrument._lock:
            command_payload = instrument.protocol.format_query(command)
            if isinstance(command_payload, str):
                command_payload = command_payload.encode("utf-8")
            return instrument.transport.query(command_payload, slow=slow)

    @staticmethod
    def _remove_binary_terminator(data: bytes, itemsize: int) -> bytes:
        """Remove a SCPI line terminator without stripping valid float bytes."""
        if len(data) % itemsize == 0:
            return data
        if data.endswith(b"\r\n") and (len(data) - 2) % itemsize == 0:
            return data[:-2]
        if data.endswith(b"\n") and (len(data) - 1) % itemsize == 0:
            return data[:-1]
        raise ValueError(
            f"Binary response has {len(data)} data bytes, which is not a whole "
            f"number of {itemsize}-byte values."
        )

    @classmethod
    def parse_binary_floats(
        cls,
        payload: bytes,
        *,
        data_format: ElectrometerDataFormat | None,
        byte_order: KeithleyByteOrder,
        count: int | None = None,
    ) -> np.ndarray:
        """View a Keithley ``#0`` IEEE-754 response as a NumPy array.

        No copy or per-value Python conversion is made.  The returned array is
        a read-only view over the response byte string.
        """
        if data_format is None:
            if count is None:
                raise ValueError("count is required when inferring the binary data format.")
            matches = []
            for candidate, itemsize in (
                (ElectrometerDataFormat.SREAL, 4),
                (ElectrometerDataFormat.DREAL, 8),
            ):
                try:
                    data = parse_ieee_block(
                        payload,
                        allow_indefinite=True,
                        itemsize=itemsize,
                    )
                except ValueError:
                    continue
                if len(data) == count * itemsize:
                    matches.append(candidate)
            if len(matches) != 1:
                raise ValueError(
                    "Binary response length does not identify one precision for "
                    f"the expected {count} values."
                )
            data_format = matches[0]
        if data_format is ElectrometerDataFormat.ASCII:
            raise ValueError("ASCII data cannot be parsed as a binary response.")
        type_code = "f4" if data_format is ElectrometerDataFormat.SREAL else "f8"
        itemsize = 4 if data_format is ElectrometerDataFormat.SREAL else 8
        if not payload.startswith(b"#0"):
            raise ValueError("Binary Keithley response does not start with the '#0' marker.")
        data = parse_ieee_block(
            payload,
            allow_indefinite=True,
            itemsize=itemsize,
        )
        endian = ">" if byte_order is KeithleyByteOrder.NORMAL else "<"
        values = np.frombuffer(data, dtype=np.dtype(f"{endian}{type_code}"))
        if count is not None:
            return values[:count]
        return values
