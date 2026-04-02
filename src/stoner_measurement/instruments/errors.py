"""Custom exceptions for the instrument driver framework.

All exceptions raised by the instrument driver layer inherit from
:exc:`InstrumentError`, allowing callers to catch the entire family with a
single ``except InstrumentError`` clause.
"""

from __future__ import annotations


class InstrumentError(Exception):
    """Raised when an instrument reports a command or execution error.

    Carries structured information about the failure so that calling code can
    log or display a meaningful diagnostic without parsing the exception
    message string.

    Attributes:
        command (str | None):
            The command string that triggered the error, or ``None`` if the
            failing command is not known.
        error_code (int | None):
            Numeric error code returned by the instrument (e.g. the SCPI
            integer before the comma in a ``SYST:ERR?`` response), or
            ``None`` for protocols that do not use numeric codes.
        message (str):
            Human-readable description of the error as reported by the
            instrument.

    Examples:
        >>> from stoner_measurement.instruments.errors import InstrumentError
        >>> exc = InstrumentError(
        ...     "Undefined header",
        ...     command="*IDN",
        ...     error_code=-113,
        ... )
        >>> exc.command
        '*IDN'
        >>> exc.error_code
        -113
        >>> str(exc)
        'Undefined header (command: *IDN, code: -113)'
    """

    def __init__(
        self,
        message: str,
        *,
        command: str | None = None,
        error_code: int | None = None,
    ) -> None:
        """Initialise the exception.

        Args:
            message (str):
                Human-readable description of the error.

        Keyword Parameters:
            command (str | None):
                The command that triggered the error.  Defaults to ``None``.
            error_code (int | None):
                Numeric error code, if available.  Defaults to ``None``.
        """
        self.command = command
        self.error_code = error_code
        self.message = message
        super().__init__(self._format())

    def _format(self) -> str:
        """Build the human-readable exception string."""
        parts: list[str] = []
        if self.command is not None:
            parts.append(f"command: {self.command}")
        if self.error_code is not None:
            parts.append(f"code: {self.error_code}")
        if parts:
            return f"{self.message} ({', '.join(parts)})"
        return self.message
