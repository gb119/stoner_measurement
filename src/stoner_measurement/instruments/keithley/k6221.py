"""Keithley 6221 AC/DC precision current-source driver."""

from __future__ import annotations

import math
import time
from enum import Enum
from time import sleep

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
_OPERATING_STATUS_SWEEP_RUNNING = 0x08
_OPERATING_STATUS_SWEEP_FINISHED = 0x02
_STATUS_BYTE_OPERATION_SUMMARY = 0x80
_STATUS_BYTE_REQUEST_SERVICE = 0x40


class _K6221_STATE(Enum):
    """Represent the current state of the Keithley 6221 to determine next actions."""

    IDLE="IDLE"
    SWEEPING="SWEEPING"
    SOURCE="SOURCE"
    WAVE="WAVE"
    ARMED="ARMED"
    ARMING="ARMING"

class Keithley6221(CurrentSource):
    """Driver for the Keithley 6221 precision AC/DC current source.

    Provides DC source-level and compliance control plus AC waveform controls
    (waveform shape, frequency, and offset current) using SCPI commands.
    Built-in staircase sweeps (linear, logarithmic, custom list) and pulsed
    sweeps are also supported.
    """

    _MODEL = "MODEL 6221"

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

    def connect(self) -> None:
        """Open the transport connection to the instrument.

        After opening the transport, any data accumulated in the transport
        buffer since the last session is discarded via
        :meth:`~stoner_measurement.instruments.transport.base.BaseTransport.flush`
        so that stale responses from previous commands cannot be misread as
        replies to new queries.

        Raises:
            ConnectionError:
                If the underlying transport cannot be opened.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> instr = BaseInstrument(NullTransport(), ScpiProtocol())
            >>> instr.connect()
            >>> instr.is_connected
            True
            >>> instr.disconnect()
        """
        super().connect()
        self.reset()
        state=self.state()
        match state:
            case _K6221_STATE.SWEEPING:
                self.sweep_abort()
            case  _K6221_STATE.SOURCE|_K6221_STATE.ARMED|_K6221_STATE.ARMING:
                self.write(":ABOR")
            case  _K6221_STATE.WAVE:
                self.wave_abort()
            case _:
                pass
        self.clear()

    def reset(self) -> None:
        """Send the standard IEEE 488.2 reset command (``*RST``).

        Instruments that do not support ``*RST`` should override this method.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> t = NullTransport()
            >>> instr = BaseInstrument(t, ScpiProtocol())
            >>> instr.connect()
            >>> instr.reset()
            >>> t.write_log
            [b'*RST\\n']
            >>> instr.disconnect()
        """
        self.write("*RST", slow=500)

    def state(self)->_K6221_STATE:
        """Determine the state of the 6221 through status queries."""
        self.clear()
        self.read_status_byte()
        outp=self.output_enabled()
        oper=self.get_operating_status()
        if not outp:
            return _K6221_STATE.IDLE
        if not oper & 120:
            return _K6221_STATE.SOURCE
        for bit,state in [(8,_K6221_STATE.SWEEPING),(16,_K6221_STATE.WAVE),(32,_K6221_STATE.ARMED),(63,_K6221_STATE.ARMING)]:
            if oper & bit:
                return state

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

    def get_waveform_amplitude(self) -> float:
        """Return AC waveform amplitude in amps."""
        return float(self.query(":SOUR:WAVE:AMPL?"))

    def set_waveform_amplitude(self, value: float) -> None:
        """Set AC waveform amplitude in amps."""
        if value < 0.0:
            raise ValueError("Waveform amplitude must be non-negative.")
        self.write(f":SOUR:WAVE:AMPL {value}")

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

    def phase_marker_enabled(self) -> bool:
        """Return ``True`` if the waveform phase marker is enabled."""
        return self.query(":SOUR:WAVE:PMAR:STAT?").strip() == "1"

    def enable_phase_marker(self, state: bool) -> None:
        """Enable or disable the waveform phase-marker output."""
        self.write(f":SOUR:WAVE:PMAR:STAT {1 if state else 0}")

    def get_phase_marker_output_line(self) -> int:
        """Return the configured phase-marker trigger-link output line."""
        return int(float(self.query(":SOUR:WAVE:PMAR:OLIN?").strip()))

    def _validate_phase_marker_output_line(self, output_line: int) -> None:
        """Validate a requested phase-marker output line number."""
        if not 1 <= output_line <= 6:
            raise ValueError("output_line must be in the range 1..6.")

    def set_phase_marker_output_line(self, output_line: int) -> None:
        """Set the phase-marker trigger-link output line."""
        self._validate_phase_marker_output_line(output_line)
        self.write(f":SOUR:WAVE:PMAR:OLIN {output_line}")

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
            if isinstance(config.delay,float):
                config.delay=[config.delay for _ in values]
            n = len(values)
            first_batch = ",".join(str(v) for v in values[:_LIST_BATCH_SIZE])
            self.write(f":SOUR:LIST:CURR {first_batch}")
            for start in range(_LIST_BATCH_SIZE, n, _LIST_BATCH_SIZE):
                batch = ",".join(str(v) for v in values[start : start + _LIST_BATCH_SIZE])
                self.write(f":SOUR:LIST:CURR:APP {batch}")
            self.write(f":SOUR:SWE:POIN {n}")
        else:
            self.write(f":SOUR:SWE:STAR {config.start}")
            self.write(f":SOUR:SWE:STOP {config.stop}")
            self.write(f":SOUR:SWE:POIN {config.points}")
        if isinstance(config.delay, float):
            self.write(f":SOUR:DEL {config.delay}")
        else:
            delay=list(config.delay)
            n = len(delay)
            first_batch = ",".join(str(v) for v in delay[:_LIST_BATCH_SIZE])
            self.write(f":SOUR:LIST:DEL {first_batch}")
            for start in range(_LIST_BATCH_SIZE, n, _LIST_BATCH_SIZE):
                batch = ",".join(str(v) for v in delay[start : start + _LIST_BATCH_SIZE])
                self.write(f":SOUR:LIST:DEL:APP {batch}")


        if config.count != 1:
            self.write(f":SOUR:SWE:COUN {config.count}")
        sleep(0.5)

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
            batch = ",".join(f"{v:.6e}" for v in values[start : start + _LIST_BATCH_SIZE])
            self.write(f":SOUR:LIST:COMP:APP {batch}")
        sleep(0.5)

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

    def configure_arm(
        self,
        source: str = "IMM",
        bypass: bool = False,
        time: float = 0,
        direction: str = "ACC",
        tlink_in: int | None = None,
        tlink_out: int | None = None,
        output: str = "None",
    ):
        """Configure the 6221 arm layer.

        Keyword Arguments:
            source (str, "IMM"):
                The ARM layer input sources, IMM, TIM, BUS, TLIN, NST, PST, MAN
            bypass (bool, False):
                Whetgher to bypass the ARM system altogether.
            time (float, 0):
                Timer to use when ARM source is TIM
            direction (str, "ACC"):
                Even when not bypassing, it is possible to skip the first ARM source event by setting this to "SOUR"
            tlink_in, tlink_out (int|None, None):
                Triggerlink lines to use when the source is "TLIN"
            output (str, "NONE"):
                Whether to indicate a transition to ("TENT") or from ("TEX") the trigger layer, or not al at all ("NONE").
        """
        if bypass:
            self.write(":ARM:SIGN")
            return
        self.write(f":ARM:DIR {direction}")
        match source.upper():
            case "IMM" | "BUS" | "NST" | "PST" | "MAN":
                self.write(f":ARM:SOUR {source.upper()}")
            case "TIM":
                self.write(":ARM:SOUR TIM")
                self.write(f":ARM:TIM {time:.2f}")
            case "TLIN":
                self.write(":ARM:SOUR TLIN")
                if tlink_in:
                    self.write(f":ARM:ILIN {tlink_in}")
                if tlink_out:
                    self.write(f":ARM:OLIN {tlink_out}")
            case _:
                raise ValueError(f"Unrecognised ARM mode {source}")
        self.write(f":ARM:OUTP {output}")

    def configure_trigger(
        self,
        source: str = "IMM",
        bypass: bool = False,
        direction: str = "ACC",
        tlink_in: int | None = None,
        tlink_out: int | None = None,
        output: str = "None",
    ):
        """Configure the trigger layer.

        Keyword Arguments:
            source (str, "IMM"):
                The Trigger layer input sources, IMM, TLIN
            bypass (bool, False):
                Whetgher to bypass the Trigger system altogether.
            direction (str, "ACC"):
                Even when not bypassing, it is possible to skip the first Trigger source event by setting this to "SOUR"
            tlink_in, tlink_out (int|None, None):
                Triggerlink lines to use when the source is "TLIN"
            output (str, "NONE"):
                When the output trigger is sent - after source ("SOUR"), after delay ("DEL"), or not ("NONE")
        """
        if bypass:
            self.write(":TRIG:SIGN")
            return
        self.write(f":TRIG:DIR {direction}")
        match source.upper():
            case "IMM":
                self.write(f":TRIG:SOUR {source.upper()}")
            case "TLIN":
                self.write(":TRIG:SOUR TLIN")
            case _:
                raise ValueError(f"Unrecognised TRIG mode {source}")
        self.write(f":TRIG:OUTP {output}")
        if source == "TLIN" or output != "NONE":
            self.configure_trigger_link(tlink_out, tlink_in)

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

        with self._lock:
            # Read current state so we know what is already assigned.
            cur_olin = int(self.query(":TRIG:OLIN?").strip())
            cur_ilin = int(self.query(":TRIG:ILIN?").strip())
            cur_pmar = int(self.query(":SOUR:WAVE:PMAR:OLIN?").strip())

            def _free_line(*excluded: int) -> int:
                """Return the lowest line in 1..6 not in *excluded*."""
                exclude_set = set(excluded)
                for line in range(1, 7):
                    if line not in exclude_set:
                        return line
                raise RuntimeError(  # pragma: no cover
                    f"No free trigger-link line available (excluded: {sorted(exclude_set)})."
                )

            # ---- Free the desired input line --------------------------------
            # TRIG:ILIN <n> fails if <n> is already assigned to TRIG:OLIN or the
            # phase-marker output.  Move whichever conflicts to a neutral line.
            if cur_olin == input_line:
                temp = _free_line(input_line, output_line, cur_ilin, cur_pmar if cur_pmar is not None else 0)
                self.write(f":TRIG:OLIN {temp}")
                cur_olin = temp
            if cur_pmar == input_line:
                temp = _free_line(input_line, output_line, cur_olin, cur_ilin)
                self.write(f":SOUR:WAVE:PMAR:OLIN {temp}")
                cur_pmar = temp

            # ---- Assign the input line --------------------------------------
            self.write(f":TRIG:ILIN {input_line}")

            # ---- Free the desired output line -------------------------------
            # TRIG:OLIN <n> fails if <n> is already assigned to TRIG:ILIN (now
            # input_line -- a user-error handled by the guard above) or the
            # phase-marker output.
            if cur_pmar == output_line:
                temp = _free_line(output_line, input_line, cur_olin)
                self.write(f":SOUR:WAVE:PMAR:OLIN {temp}")

            # ---- Assign the output line and fix trigger direction -----------
            self.write(f":TRIG:OLIN {output_line}")

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
        raw = self.transport.read_until(terminator)
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

        Notes:
            This will terminate after if recieves a blank chunk after it
            recieves a non-blank chunk.
        """
        if max_chunks <= 0:
            raise ValueError("max_chunks must be positive.")
        self.send_serial_command(cmd, terminator=command_terminator)
        sleep(0.1)
        parts: list[str] = []
        for _ in range(max_chunks):
            chunk = self._read_serial_entry_chunk().strip()
            if chunk:
                parts.append(chunk)
            else:
                sleep(0.05)
            if parts and not chunk:
                break
        else:
            raise RuntimeError("Timed out reading serial relay response: no line terminator (LF) received.")
        combined = "".join(parts)
        return combined.rstrip("\r\n")

    def sweep_arm(self) -> None:
        """Arm the configured sweep."""
        self.enable_output(True)
        self.write(":SOUR:SWE:ARM")

    def sweep_init(self) -> None:
        """Manually trigger the arm layer for a sweep."""
        self.write(":INIT:IMM")

    def sweep_start(self) -> None:
        """Arm the configured sweep, making it ready for triggering."""
        self.sweep_arm()
        self.sweep_init()

    def sweep_abort(self) -> None:
        """Abort a running or armed sweep."""
        self.write(":SOUR:SWE:ABOR")

    def get_operating_status(self) -> int:
        """Return the current operating-status condition register."""
        return int(float(self.query(":STAT:OPER:COND?")))

    def configure_sweep_complete_srq(self) -> None:
        """Route the sweep-finished operating event to the SRQ line."""
        self.write(f":STAT:OPER:ENAB {_OPERATING_STATUS_SWEEP_FINISHED}")
        self.write(f"*SRE {_STATUS_BYTE_OPERATION_SUMMARY}")

    def clear_sweep_complete_event(self) -> None:
        """Clear a sweep event latched by an earlier acquisition."""
        self.query(":STAT:OPER:EVEN?")

    def wait_for_sweep_complete_srq(self, timeout: float, poll_interval: float = 0.01) -> bool:
        """Wait for sweep SRQ, using a transport-native operation if available."""
        native_result = self.transport.wait_for_srq(timeout)
        if native_result is not None:
            self.transport._log_comms_traffic("IEEE", f"SRQ Asserted {native_result}")
            return native_result

        deadline = time.monotonic() + timeout
        while time.monotonic() <= deadline:
            with self._lock:
                auto_check_errors = self.auto_check_errors
                self.auto_check_errors = False
                try:
                    status_byte = int(float(self.query("*STB?")))
                finally:
                    self.auto_check_errors = auto_check_errors
            if status_byte & _STATUS_BYTE_REQUEST_SERVICE:
                self.transport._log_comms_traffic("IEEE", f"SRQ from Status byte asserteed {status_byte}")
                return True
            sleep(poll_interval)
        self.transport._log_comms_traffic("IEEE", "Timed out waiting for SRQ")
        return False

    def sweep_is_running(self) -> bool:
        """Return ``True`` while the instrument reports an active sweep."""
        return bool(self.get_operating_status() & _OPERATING_STATUS_SWEEP_RUNNING)

    def sweep_is_finished(self) -> bool:
        """Return ``True`` when the operating-status register reports sweep completion."""
        return bool(self.get_operating_status() & _OPERATING_STATUS_SWEEP_FINISHED)

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

    @staticmethod
    def validate_pulse_delta_sweep(
        values: tuple[float, ...],
        *,
        width: float,
        source_delay: float,
        period: float,
        low_measurements: int,
    ) -> None:
        """Validate native Pulse Delta settings before any instrument writes.

        Args:
            values (tuple[float, ...]): High pulse currents in amps.

        Keyword Parameters:
            width (float): Pulse width, 50 microseconds to 12 milliseconds.
            source_delay (float): Settling time within a pulse, in seconds.
            period (float): Requested cycle period in seconds.
            low_measurements (int): One or two baseline measurements.

        Raises:
            ValueError: If a list or timing setting is outside its limits.
        """
        if not 1 <= len(values) <= 65536:
            raise ValueError("Pulse Delta requires 1 to 65536 current points.")
        if any(not math.isfinite(v) or abs(v) > 0.105 for v in values):
            raise ValueError("Pulse currents must be finite and within +/-105 mA.")
        if not math.isfinite(width) or not 50e-6 <= width <= 12e-3:
            raise ValueError("Pulse width must be between 50 us and 12 ms.")
        if not math.isfinite(source_delay) or not 16e-6 <= source_delay <= 11.966e-3:
            raise ValueError("Pulse source delay must be between 16 us and 11.966 ms.")
        if source_delay >= width:
            raise ValueError("Pulse source delay must be shorter than the pulse width.")
        if not math.isfinite(period) or not 1e-3 <= period <= 999999.999 or period < width:
            raise ValueError(
                "Pulse cycle period must be 1 ms to 999999.999 s and exceed the width."
            )
        if type(low_measurements) is not int or low_measurements not in (1, 2):
            raise ValueError("Pulse Delta requires one or two low measurements.")

    def configure_pulse_delta_sweep(
        self,
        values: tuple[float, ...],
        *,
        width: float,
        source_delay: float,
        period: float,
        low_measurements: int = 2,
    ) -> None:
        """Programme a native zero-baseline Pulse Delta custom sweep.

        Requires a 2182A connected by RS-232 and Trigger Link. Does not arm
        or start output. See reference manual sections 5-37 to 5-50.

        Args:
            values (tuple[float, ...]): High pulse currents in amps.

        Keyword Parameters:
            width (float): Pulse width in seconds.
            source_delay (float): Settling delay within each pulse in seconds.
            period (float): Requested complete cycle period in seconds.
            low_measurements (int): Number of baseline measurements, 1 or 2.

        Raises:
            ValueError: If the current list or pulse timing is invalid.
        """
        self.validate_pulse_delta_sweep(
            values,
            width=width,
            source_delay=source_delay,
            period=period,
            low_measurements=low_measurements,
        )
        with self._lock:
            self.configure_custom_sweep(values, delay=float(period), count=1)
            self.set_sweep_count(1)
            self.write(":SOUR:PDEL:LOW 0")
            self.write(f":SOUR:PDEL:WIDT {width}")
            self.write(f":SOUR:PDEL:SDEL {source_delay}")
            self.write(f":SOUR:PDEL:LME {low_measurements}")
            self.write(":SOUR:PDEL:SWE ON")
            self.write(":UNIT V")
            self.write(":SENS:AVER:STAT OFF")

    def pulse_delta_present(self) -> bool:
        """Return whether a compatible 2182A is connected over RS-232."""
        return self.query(":SOUR:PDEL:NVPR?").strip() == "1"

    def set_pulse_delta_voltage_range(self, value: float) -> None:
        """Set the 2182A range through serial; zero selects autorange.

        Args:
            value (float): Voltage range in volts, or zero for autorange.

        Raises:
            ValueError: If the voltage range is invalid.
        """
        if not math.isfinite(value) or value not in (0, 0.01, 0.1, 1, 10, 100):
            raise ValueError("2182A range must be auto (0), 0.01, 0.1, 1, 10 or 100 V.")
        with self._lock:
            self.send_serial_command(f":SENS:VOLT:CHAN1:RANG:AUTO {int(value == 0)}")
            if value:
                self.send_serial_command(f":SENS:VOLT:CHAN1:RANG {value}")

    def pulse_delta_arm(self) -> None:
        """Arm Pulse Delta, allowing time for the internal sweep table build.

        Raises:
            RuntimeError: If the instrument does not confirm the armed state.
        """
        with self._lock:
            timeout = self.transport.timeout
            try:
                self.transport.timeout = max(timeout, 120.0)
                self.write(":SOUR:PDEL:ARM")
                if self.query(":SOUR:PDEL:ARM?").strip() != "1":
                    raise RuntimeError("6221 did not arm Pulse Delta.")
            finally:
                self.transport.timeout = timeout

    def prepare_pulse_delta_buffer(self, count: int) -> None:
        """Clear and enable the 6221 buffer for one complete pulse sweep.

        Args:
            count (int): Number of corrected voltages to store, 1 to 65536.

        Raises:
            ValueError: If the requested buffer size is invalid.
        """
        if type(count) is not int or not 1 <= count <= 65536:
            raise ValueError("Pulse Delta buffer size must be 1 to 65536.")
        with self._lock:
            self.write(":TRAC:FEED:CONT NEV")
            self.write(":TRAC:CLE")
            self.write(f":TRAC:POIN {count}")
            self.write(":FORM:DATA ASC")
            self.write(":FORM:ELEM READ")
            self.write(":TRAC:FEED SENS1")
            self.write(":TRAC:FEED:CONT NEXT")

    def pulse_delta_buffer_count(self) -> int:
        """Return the number of corrected readings committed to the 6221 buffer."""
        return int(self.query(":TRAC:POIN:ACT?").strip())

    def read_pulse_delta_buffer(self, count: int) -> tuple[float, ...]:
        """Read corrected voltages, rejecting incomplete or malformed buffers.

        Args:
            count (int): Expected number of readings.

        Returns:
            (tuple[float, ...]): Corrected pulse voltages in volts.

        Raises:
            ValueError: If the buffer response is malformed or incomplete.
        """
        values = tuple(float(v) for v in self.query(":TRAC:DATA?").strip().split(","))
        if len(values) != count:
            raise ValueError(f"Expected {count} Pulse Delta readings, received {len(values)}.")
        return values

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

    def wave_abort(self)->None:
        """Abort a runnign waveform."""
        self.write("SOUR:WAVE:ABOR")

    def wave_start(self)->None:
        """Arm the wave outpit."""
        self.write("SOUR:WAVE:ARM")
        self.write("SOUR:WAVE:INIT")
