"""Native FTDI D2XX byte-stream transport.

This module deliberately wraps only the small, stable D2XX API surface needed
by legacy laboratory interfaces: open, close, purge, read and write.  Protocol
framing and interpretation remain the responsibility of the instrument driver.
"""

from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path

from stoner_measurement.instruments.transport.base import BaseTransport

_FT_OK = 0
_FT_OPEN_BY_SERIAL_NUMBER = 1
_FT_PURGE_RX = 1
_FT_PURGE_TX = 2


class FtdiD2xxError(OSError):
    """An FTDI D2XX operation failed."""


class FtdiD2xxTransport(BaseTransport):
    """Access an FTDI device directly through the native D2XX library.

    Args:
        device (int | str): Zero-based device index, or FTDI serial number.

    Keyword Parameters:
        dll_path (str | Path | None): Explicit path to ``ftd2xx.dll``.  When
            omitted the platform loader searches its normal locations.
        timeout (float): Read timeout in seconds.
        write_timeout (float): Write timeout in seconds.
    """

    def __init__(
        self,
        device: int | str = 0,
        *,
        dll_path: str | Path | None = None,
        timeout: float = 2.0,
        write_timeout: float = 2.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.device = device
        self.dll_path = Path(dll_path) if dll_path is not None else None
        self.write_timeout = float(write_timeout)
        self._library: ctypes.CDLL | None = None
        self._handle = ctypes.c_void_p()

    @property
    def transport_address(self) -> str:
        """Return a stable D2XX resource identifier."""
        selector = f"serial:{self.device}" if isinstance(self.device, str) else f"index:{self.device}"
        return f"FTDI::{selector}"

    def open(self) -> None:
        """Load D2XX and open the selected FTDI device."""
        if self._is_open:
            return
        library = self._load_library()
        self._configure_signatures(library)
        handle = ctypes.c_void_p()
        if isinstance(self.device, str):
            serial = self.device.encode("ascii")
            status = library.FT_OpenEx(
                ctypes.c_char_p(serial), _FT_OPEN_BY_SERIAL_NUMBER, ctypes.byref(handle)
            )
        else:
            status = library.FT_Open(int(self.device), ctypes.byref(handle))
        self._check(status, "open device")
        self._library = library
        self._handle = handle
        self._is_open = True
        try:
            self._set_timeouts()
        except Exception:
            self.close()
            raise
        self._log_comms_traffic("IEEE", "Connection opened.")

    def close(self) -> None:
        """Close the selected FTDI device."""
        if self._library is not None and self._handle.value:
            status = self._library.FT_Close(self._handle)
            self._handle = ctypes.c_void_p()
            self._is_open = False
            self._check(status, "close device")
        self._is_open = False

    def write(self, data: bytes, slow: int | None = None) -> int:
        """Write *data* exactly as supplied, without a terminator."""
        library = self._require_open()
        payload = bytes(data)
        buffer = ctypes.create_string_buffer(payload, len(payload))
        written = ctypes.c_ulong()
        status = library.FT_Write(
            self._handle, buffer, len(payload), ctypes.byref(written)
        )
        self._check(status, "write")
        if written.value != len(payload):
            raise FtdiD2xxError(
                f"D2XX short write: requested {len(payload)} byte(s), wrote {written.value}."
            )
        self._log_comms_traffic("TX", payload)
        if slow is not None:
            time.sleep(slow / 1000.0)
        return 0

    def read(self, num_bytes: int | None = None) -> bytes:
        """Read up to the requested fixed frame size before the timeout."""
        library = self._require_open()
        requested = self._resolve_max_frame_size(num_bytes)
        deadline = time.monotonic() + self.timeout
        result = bytearray()
        while len(result) < requested:
            queued = ctypes.c_ulong()
            self._check(
                library.FT_GetQueueStatus(self._handle, ctypes.byref(queued)),
                "query receive queue",
            )
            available = min(int(queued.value), requested - len(result))
            if available:
                buffer = ctypes.create_string_buffer(available)
                received = ctypes.c_ulong()
                self._check(
                    library.FT_Read(
                        self._handle, buffer, available, ctypes.byref(received)
                    ),
                    "read",
                )
                result.extend(buffer.raw[: received.value])
                continue
            if time.monotonic() >= deadline:
                break
            time.sleep(0.001)
        if not result:
            raise TimeoutError(
                f"No data received from {self.transport_address!r} within {self.timeout}s."
            )
        data = bytes(result)
        self._log_comms_traffic("RX", data)
        return data

    def flush(self) -> None:
        """Purge both native D2XX receive and transmit queues."""
        if not self._is_open:
            return
        library = self._require_open()
        self._check(
            library.FT_Purge(self._handle, _FT_PURGE_RX | _FT_PURGE_TX),
            "purge queues",
        )

    def _apply_timeout(self, value: float) -> None:
        if self._is_open:
            self._set_timeouts()

    def _set_timeouts(self) -> None:
        library = self._require_open()
        read_ms = max(0, round(self.timeout * 1000.0))
        write_ms = max(0, round(self.write_timeout * 1000.0))
        self._check(
            library.FT_SetTimeouts(self._handle, read_ms, write_ms),
            "set timeouts",
        )

    def _load_library(self) -> ctypes.CDLL:
        target = str(self.dll_path) if self.dll_path is not None else "ftd2xx.dll"
        try:
            loader = ctypes.WinDLL if os.name == "nt" else ctypes.CDLL
            return loader(target)
        except OSError as exc:
            raise ImportError(
                "Unable to load the FTDI D2XX library. Install the matching "
                "FTDI D2XX driver or provide dll_path explicitly."
            ) from exc

    @staticmethod
    def _configure_signatures(library: ctypes.CDLL) -> None:
        library.FT_Open.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        library.FT_Open.restype = ctypes.c_ulong
        library.FT_OpenEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)]
        library.FT_OpenEx.restype = ctypes.c_ulong
        library.FT_Close.argtypes = [ctypes.c_void_p]
        library.FT_Close.restype = ctypes.c_ulong
        library.FT_Read.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        library.FT_Read.restype = ctypes.c_ulong
        library.FT_Write.argtypes = list(library.FT_Read.argtypes)
        library.FT_Write.restype = ctypes.c_ulong
        library.FT_SetTimeouts.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
        library.FT_SetTimeouts.restype = ctypes.c_ulong
        library.FT_GetQueueStatus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        library.FT_GetQueueStatus.restype = ctypes.c_ulong
        library.FT_Purge.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        library.FT_Purge.restype = ctypes.c_ulong

    def _require_open(self) -> ctypes.CDLL:
        if not self._is_open or self._library is None or not self._handle.value:
            raise ConnectionError("FTDI D2XX device is not open.")
        return self._library

    @staticmethod
    def _check(status: int, operation: str) -> None:
        if status != _FT_OK:
            raise FtdiD2xxError(f"D2XX failed to {operation} (FT_STATUS={status}).")
