"""Oxford Mercury native newline framing with errors in READ/SET replies."""

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol


class MercuryProtocol(ScpiProtocol):
    """Frame Mercury commands without polling the unsupported SCPI error queue."""

    def __init__(self, terminator: bytes = b"\n", *, max_frame_size: int = 1024):
        """Use Mercury's documented maximum native line length."""
        super().__init__(terminator=terminator, max_frame_size=max_frame_size)

    @property
    def errors_in_response(self) -> bool:
        """Return True because Mercury reports failures inline."""
        return True

    @property
    def error_query(self) -> None:
        """Return None: Mercury does not implement SYST:ERR?."""
        return None

    def check_error(self, response: str, *, command: str | None = None) -> None:
        """Raise for native Mercury command failures.

        Args:
            response (str): Decoded native reply.

        Keyword Parameters:
            command (str | None): Command associated with the reply.

        Raises:
            InstrumentError: A native rejection token occurs in the reply.
        """
        if any(token in {"INVALID", "NOT_FOUND", "N/A", "DENIED"} for token in response.split(":")):
            raise InstrumentError(f"Mercury: {response}", command=command)
