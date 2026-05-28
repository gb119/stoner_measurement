"""Keithley 6221 AC/DC precision current-source driver."""

from __future__ import annotations

from stoner_measurement.instruments.current_source import (
    CurrentSource,
    CurrentSourceCapabilities,
    CurrentSweepConfiguration,
    CurrentSweepSpacing,
    CurrentWaveform,
    PulsedSweepConfiguration,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

#: Maximum number of values the 6221 accepts in a single :SOUR:LIST:CURR or
#: :SOUR:LIST:COMP command. Longer lists are split and appended in batches.
_LIST_BATCH_SIZE: int = 100


class Keithley6221(CurrentSource):
    """Driver for the Keithley 6221 precision AC/DC current source.

    Provides DC source-level and compliance control plus AC waveform controls
    (waveform shape, frequency, and offset current) using SCPI commands.
    Built-in staircase sweeps (linear, logarithmic, custom list) and pulsed
    sweeps are also supported.
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
    ) -> None:
        """Initialise the Keithley 6221 driver, defaulting to :class:`ScpiProtocol`."""
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )

    def get_source_level(self) -> float:
        """Return programmed source current in amps."""
        return float(self.query(":SOUR:CURR?"))

    def set_source_level(self, value: float) -> None:
        """Set source current in amps."""
        self.write(f":SOUR:CURR {value}")

    def get_compliance_voltage(self) -> float:
        """Return compliance voltage in volts."""
        return float(self.query(":SOUR:CURR:COMP?"))

    def set_compliance_voltage(self, value: float) -> None:
        """Set compliance voltage in volts."""
        self.write(f":SOUR:CURR:COMP {value}")

    def output_enabled(self) -> bool:
        """Return ``True`` if source output is enabled."""
        return self.query(":OUTP:STAT?") == "1"

    def enable_output(self, state: bool) -> None:
        """Enable or disable source output."""
        self.write(f":OUTP:STAT {1 if state else 0}")

    def get_waveform(self) -> CurrentWaveform:
        """Return waveform mode."""
        token = self.query(":SOUR:WAVE:FUNC?").strip().upper()
        if token.startswith("SIN"):
            return CurrentWaveform.SINE
        return CurrentWaveform(token)

    def set_waveform(self, waveform: CurrentWaveform) -> None:
        """Set waveform mode."""
        token = "SIN" if waveform is CurrentWaveform.SINE else waveform.value
        self.write(f":SOUR:WAVE:FUNC {token}")

    def get_frequency(self) -> float:
        """Return AC waveform frequency in Hz."""
        return float(self.query(":SOUR:WAVE:FREQ?"))

    def set_frequency(self, value: float) -> None:
        """Set AC waveform frequency in Hz."""
        if value <= 0.0:
            raise ValueError("Frequency must be positive.")
        self.write(f":SOUR:WAVE:FREQ {value}")

    def get_offset_current(self) -> float:
        """Return AC waveform DC offset current in amps."""
        return float(self.query(":SOUR:WAVE:OFFS?"))

    def set_offset_current(self, value: float) -> None:
        """Set AC waveform DC offset current in amps."""
        self.write(f":SOUR:WAVE:OFFS {value}")

    def configure_sweep(self, config: CurrentSweepConfiguration) -> None:
        """Configure a built-in current sweep.

        For ``LIST`` spacing the values list is written to the instrument in
        batches of :data:`_LIST_BATCH_SIZE` (100) points using the
        ``SOUR:LIST:CURR:APP`` append command so that sweeps longer than 100
        points are handled transparently.

        Args:
            config (CurrentSweepConfiguration):
                Sweep configuration.  For :attr:`~CurrentSweepSpacing.LIST`
                spacing, ``config.values`` must be non-empty.

        Raises:
            ValueError:
                If ``config.spacing`` is ``LIST`` and ``config.values`` is
                empty or ``None``.

        Examples:
            >>> from stoner_measurement.instruments.keithley.k6221 import Keithley6221, _LIST_BATCH_SIZE
            >>> from stoner_measurement.instruments.current_source import (
            ...     CurrentSweepConfiguration, CurrentSweepSpacing)
            >>> from stoner_measurement.instruments.transport.base import BaseTransport
        """
        self.write(f":SOUR:SWE:SPAC {config.spacing.value}")
        if config.spacing is CurrentSweepSpacing.LIST:
            if not config.values:
                raise ValueError("LIST sweep requires non-empty values.")
            values = list(config.values)
            n = len(values)
            first_batch = ",".join(str(v) for v in values[:_LIST_BATCH_SIZE])
            self.write(f":SOUR:LIST:CURR {first_batch}")
            for start in range(_LIST_BATCH_SIZE, n, _LIST_BATCH_SIZE):
                batch = ",".join(str(v) for v in values[start:start + _LIST_BATCH_SIZE])
                self.write(f":SOUR:LIST:CURR:APP {batch}")
            self.write(f":SOUR:SWE:POIN {n}")
        else:
            self.write(f":SOUR:SWE:STAR {config.start}")
            self.write(f":SOUR:SWE:STOP {config.stop}")
            self.write(f":SOUR:SWE:POIN {config.points}")
        self.write(f":SOUR:DEL {config.delay}")
        if config.count != 1:
            self.write(f":SOUR:SWE:COUN {config.count}")

    def configure_list_compliance(self, values: list[float]) -> None:
        """Configure per-point compliance voltages for a LIST sweep.

        Sends the compliance voltage list to the instrument in batches of
        :data:`_LIST_BATCH_SIZE` (100) points, using
        ``SOUR:LIST:COMP:APP`` to append batches beyond the first.

        Args:
            values (list[float]):
                Per-point compliance voltages in volts.  Must not be empty.

        Raises:
            ValueError:
                If *values* is empty.

        Examples:
            >>> from stoner_measurement.instruments.keithley.k6221 import Keithley6221
            >>> # k.configure_list_compliance([10.0, 10.0, 10.0])  # per-point compliance
        """
        if not values:
            raise ValueError("values must be non-empty.")
        n = len(values)
        first_batch = ",".join(f"{v:.6e}" for v in values[:_LIST_BATCH_SIZE])
        self.write(f":SOUR:LIST:COMP {first_batch}")
        for start in range(_LIST_BATCH_SIZE, n, _LIST_BATCH_SIZE):
            batch = ",".join(f"{v:.6e}" for v in values[start:start + _LIST_BATCH_SIZE])
            self.write(f":SOUR:LIST:COMP:APP {batch}")

    def set_sweep_range_mode(self, mode: str) -> None:
        """Set sweep range mode.

        Args:
            mode (str):
                Sweep range mode token.  Supported values are ``"AUTO"``
                and ``"BEST"`` (case-insensitive).

        Raises:
            ValueError:
                If *mode* is not ``"AUTO"`` or ``"BEST"``.
        """
        token = mode.strip().upper()
        if token not in {"AUTO", "BEST"}:
            raise ValueError("mode must be 'AUTO' or 'BEST'.")
        self.write(f":SOUR:SWE:RANG {token}")

    def set_fixed_range(self, value: float) -> None:
        """Set a fixed source-current range.

        Args:
            value (float):
                Fixed current range in amps.

        Raises:
            ValueError:
                If *value* is not positive.
        """
        if value <= 0.0:
            raise ValueError("Fixed range must be positive.")
        self.write(f":SOUR:CURR:RANG {value:.6e}")

    def set_sweep_count(self, count: int) -> None:
        """Set sweep repeat count.

        Args:
            count (int):
                Number of sweep repetitions.

        Raises:
            ValueError:
                If *count* is not positive.
        """
        if count <= 0:
            raise ValueError("Sweep count must be positive.")
        self.write(f":SOUR:SWE:COUN {count}")

    def configure_trigger_link(self, output_line: int, input_line: int) -> None:
        """Configure trigger-link lines and trigger direction.

        The 6221 raises a settings-conflict error if the requested line is
        already allocated to one of the other two trigger-link purposes
        (input line, output line, or waveform phase-marker output line).
        This method avoids those conflicts by:

        1. Reading the current output-line, input-line, and phase-marker
           output-line assignments.
        2. Moving any conflicting assignment to a temporary free line before
           writing each of the two new assignments.
        3. Writing the new output and input lines in a safe order.

        Args:
            output_line (int):
                Trigger-link output line on the 6221 (valid range: 1..6).
            input_line (int):
                Trigger-link input line on the 6221 (valid range: 1..6).

        Raises:
            ValueError:
                If either line number is outside ``1..6`` or if
                ``output_line == input_line``.
        """
        if not 1 <= output_line <= 6:
            raise ValueError("output_line must be in the range 1..6.")
        if not 1 <= input_line <= 6:
            raise ValueError("input_line must be in the range 1..6.")
        if output_line == input_line:
            raise ValueError("output_line and input_line must be different.")

        # Read current state so we know what is already assigned.
        cur_olin = int(self.query(":TRIG:OLIN?").strip())
        cur_ilin = int(self.query(":TRIG:ILIN?").strip())
        pmar_active = self.query(":SOUR:WAVE:PMAR:STAT?").strip() == "1"
        cur_pmar: int | None = (
            int(self.query(":SOUR:WAVE:PMAR:OLIN?").strip()) if pmar_active else None
        )

        def _free_line(*excluded: int) -> int:
            """Return the lowest line in 1..6 not in *excluded*."""
            exclude_set = set(excluded)
            for line in range(1, 7):
                if line not in exclude_set:
                    return line
            raise RuntimeError("No free trigger-link line available.")  # pragma: no cover

        # ---- Free the desired input line ------------------------------------
        # TRIG:ILIN <n> fails if <n> is already assigned to TRIG:OLIN or the
        # phase-marker output.  Move whichever conflicts to a neutral line.
        if cur_olin == input_line:
            temp = _free_line(input_line, output_line, cur_ilin,
                              cur_pmar if cur_pmar is not None else 0)
            self.write(f":TRIG:OLIN {temp}")
            cur_olin = temp
        if cur_pmar is not None and cur_pmar == input_line:
            temp = _free_line(input_line, output_line, cur_olin, cur_ilin)
            self.write(f":SOUR:WAVE:PMAR:OLIN {temp}")
            cur_pmar = temp

        # ---- Assign the input line ------------------------------------------
        self.write(f":TRIG:ILIN {input_line}")
        cur_ilin = input_line  # noqa: F841 — kept to document state

        # ---- Free the desired output line -----------------------------------
        # TRIG:OLIN <n> fails if <n> is already assigned to TRIG:ILIN (now
        # input_line — a user-error handled by the guard above) or the
        # phase-marker output.
        if cur_pmar is not None and cur_pmar == output_line:
            temp = _free_line(output_line, input_line, cur_olin)
            self.write(f":SOUR:WAVE:PMAR:OLIN {temp}")

        # ---- Assign the output line and fix trigger direction ---------------
        self.write(f":TRIG:OLIN {output_line}")
        self.write(":TRIG:DIR ACC")

    @staticmethod
    def _serial_send_payload(cmd: str, terminator: str) -> str:
        """Return a relay-safe serial payload string.

        Args:
            cmd (str):
                Command string to relay.
            terminator (str):
                Serial command terminator to append (for example ``"\\r\\n"``).

        Returns:
            (str):
                Command with exactly one trailing *terminator* and doubled
                double-quotes for safe insertion in a SCPI quoted string.
        """
        command = cmd.rstrip("\r\n")
        payload = f"{command}{terminator}"
        return payload.replace('"', '""')

    def send_serial_command(self, cmd: str, *, terminator: str = "\r\n") -> None:
        """Relay a serial command through the 6221.

        Args:
            cmd (str):
                Command to send to the downstream serial instrument.

        Keyword Parameters:
            terminator (str):
                Serial command terminator appended once to *cmd*.
        """
        payload = self._serial_send_payload(cmd, terminator)
        self.write(f'SYST:COMM:SER:SEND "{payload}"')

    def _read_serial_entry_chunk(self) -> str:
        """Read one relay payload chunk from ``SYST:COMM:SER:ENT?``.

        Returns:
            (str):
                Decoded chunk from the relay response.  The outer protocol
                query terminator is removed; payload CR/LF from the downstream
                instrument is preserved.
        """
        protocol = self.protocol
        terminator = getattr(protocol, "terminator", b"\n")
        payload = protocol.format_query("SYST:COMM:SER:ENT?")
        self.transport.write(payload)
        self._log_comms_traffic("TX", payload)
        raw = self.transport.read_until(terminator)
        self._log_comms_traffic("RX", raw)
        if raw.endswith(terminator):
            raw = raw[: -len(terminator)]
        return raw.decode("utf-8", errors="replace")

    def query_serial_command(
        self,
        cmd: str,
        *,
        command_terminator: str = "\r\n",
        response_terminator: str = "\n",
        max_chunks: int = 64,
    ) -> str:
        """Relay a serial query and return the line response.

        Args:
            cmd (str):
                Query command to send to the downstream serial instrument.

        Keyword Parameters:
            command_terminator (str):
                Terminator appended to *cmd* before relay transmission.
            response_terminator (str):
                Line terminator that marks completion of the response.
            max_chunks (int):
                Maximum number of relay chunks to read while waiting for the
                terminator.

        Returns:
            (str):
                Response string with trailing CR/LF stripped.

        Raises:
            ValueError:
                If *max_chunks* is not positive.
            RuntimeError:
                If a line-terminated response is not received within
                *max_chunks* chunks.
        """
        if max_chunks <= 0:
            raise ValueError("max_chunks must be positive.")
        self.send_serial_command(cmd, terminator=command_terminator)
        parts: list[str] = []
        for _ in range(max_chunks):
            chunk = self._read_serial_entry_chunk()
            parts.append(chunk)
            combined = "".join(parts)
            if combined.endswith(response_terminator):
                return combined.rstrip("\r\n")
        raise RuntimeError(
            "Timed out reading serial relay response: no line terminator (LF) received."
        )

    def sweep_start(self) -> None:
        """Arm the configured sweep, making it ready for triggering."""
        self.write(":SOUR:SWE:ARM")

    def sweep_abort(self) -> None:
        """Abort a running or armed sweep."""
        self.write(":SOUR:SWE:ABOR")

    def configure_pulsed_sweep(
        self,
        sweep: CurrentSweepConfiguration,
        pulse: PulsedSweepConfiguration,
    ) -> None:
        """Configure a pulsed current sweep.

        Calls :meth:`configure_sweep` to programme the sweep points, then
        enables pulsed mode and sets pulse timing parameters.

        Args:
            sweep (CurrentSweepConfiguration):
                Sweep point configuration.
            pulse (PulsedSweepConfiguration):
                Pulse timing and baseline current.  ``pulse.width`` and
                ``pulse.off_time`` must both be positive.

        Raises:
            ValueError:
                If ``pulse.width`` or ``pulse.off_time`` is not positive.
        """
        if pulse.width <= 0.0:
            raise ValueError("Pulse width must be positive.")
        if pulse.off_time <= 0.0:
            raise ValueError("Pulse off_time must be positive.")
        self.configure_sweep(sweep)
        self.write(":SOUR:PULS:STAT 1")
        self.write(f":SOUR:PULS:WIDT {pulse.width}")
        self.write(f":SOUR:PULS:DEL {pulse.off_time}")
        self.write(f":SOUR:PULS:CURR:LOW {pulse.low_level}")

    def get_capabilities(self) -> CurrentSourceCapabilities:
        """Return static capabilities for Keithley 6221."""
        return CurrentSourceCapabilities(
            has_waveform_selection=True,
            has_frequency_control=True,
            has_offset_current=True,
            has_balanced_outputs=False,
            has_sweep=True,
            has_pulsed_sweep=True,
            channel_count=1,
        )
