"""ASCII protocol used by SIGNAL RECOVERY 7200-series instruments."""

from __future__ import annotations

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.protocol.base import BaseProtocol

SIGNAL_RECOVERY_MAX_FRAME_SIZE = 4 * 1024 * 1024


class SignalRecoveryPromptError(InstrumentError):
    """Raised when an RS-232 response ends with the 7265 error prompt."""


class SignalRecoveryProtocol(BaseProtocol):
    """Format 7265 commands and remove its optional RS-232 prompt.

    The 7265 uses the command mnemonic without parameters as a query.  Thus
    command and query formatting are deliberately identical.  On RS-232 the
    response terminator is followed by ``*`` for success or ``?`` for error;
    GPIB responses need not contain a prompt.
    """

    def __init__(
        self,
        terminator: bytes = b"\r\n",
        *,
        max_frame_size: int = SIGNAL_RECOVERY_MAX_FRAME_SIZE,
    ) -> None:
        self.terminator = terminator
        self.gpib_terminator = terminator
        self._max_frame_size = max_frame_size

    @property
    def max_frame_size(self) -> int:
        """Return the largest accepted response frame."""
        return self._max_frame_size

    @property
    def errors_in_response(self) -> bool:
        """Return true because RS-232 prompt errors are response-embedded."""
        return True

    def format_command(self, command: str) -> bytes:
        """Encode a command with the configured terminator."""
        return command.encode("ascii") + self.terminator

    def format_query(self, query: str) -> bytes:
        """Encode a query; the 7265 does not use a question-mark suffix."""
        return self.format_command(query)

    def parse_response(self, raw: bytes, *, command: str | None = None) -> str:
        """Decode a response, removing terminators and a success prompt."""
        response = raw.decode("ascii", errors="replace").strip()
        if response.endswith("?"):
            raise SignalRecoveryPromptError("SIGNAL RECOVERY error prompt", command=command)
        if response.endswith("*"):
            response = response[:-1].rstrip()
        return response
