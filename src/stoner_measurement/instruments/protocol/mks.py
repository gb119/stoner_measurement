"""Custom ASCII protocols for MKS controller families."""

from __future__ import annotations

from stoner_measurement.instruments.protocol.base import BaseProtocol


class MKSPR4000Protocol(BaseProtocol):
    """PR4000B-S compact ASCII protocol with carriage-return framing."""

    terminator = b"\r"

    @property
    def max_frame_size(self) -> int:
        return 128

    def format_command(self, command: str) -> bytes:
        return f"{command}\r".encode("ascii")

    def format_query(self, query: str) -> bytes:
        return f"{query}\r".encode("ascii")

    def parse_response(self, raw: bytes, *, command: str | None = None) -> str:
        _ = command
        return raw.decode("ascii", errors="strict").strip("\r\n")


class MKSPSRProtocol(BaseProtocol):
    """PSR-family ASCII protocol using CR for commands and CRLF replies."""

    terminator = b"\n"

    @property
    def max_frame_size(self) -> int:
        return 4096

    def format_command(self, command: str) -> bytes:
        return f"{command}\r".encode("ascii")

    def format_query(self, query: str) -> bytes:
        return f"{query}\r".encode("ascii")

    def parse_response(self, raw: bytes, *, command: str | None = None) -> str:
        _ = command
        return raw.decode("ascii", errors="strict").strip("\r\n")
