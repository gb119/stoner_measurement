# Signal Recovery 7265 programming guide

The 7265 is a DSP dual‑phase lock‑in amplifier with a richer, more modern feature set than the SR830—wider frequency
range, more flexible reference handling, deeper buffering, and built‑in experiments. It “uses the latest digital signal
processing (DSP) technology to extend the operating capabilities of the lock-in amplifier to provide the researcher
with a very versatile unit suitable both for measurement and control of experiments.”

Your LLM coding agent should treat the 7265 as:

A stateful instrument with multiple operating modes (signal recovery, vector voltmeter, dual reference, harmonic
analysis).

A command/response device over GPIB or RS232, with subtle protocol differences from the SR830.

A data source and controller with ADCs, DACs, curve buffers, and built‑in sweeps.

The attached application note explicitly shows that “the majority of user-developed software programs written to
operate the SR830 lock-in amplifier are easily modified to use the SIGNAL RECOVERY models 7225 and 7265 Digital Signal
Processing (DSP) instruments instead.”

Core capabilities of the 7265 (for the agent’s mental model)
Measurement & signal processing

Frequency range:
1
 mHz
→
250
 kHz
 internal reference; reference frequency may differ from oscillator frequency.

Dual‑phase lock‑in: X, Y, R, θ, noise; vector voltmeter mode.

Time constants:
10

𝜇
s
→
100
 ks
 in a 1–2–5–10 sequence via TC n.

Filter slopes: 6, 12, 18, 24 dB/oct via SLOPE n.

Line‑frequency notch: LF n1 n2 for F, 2F, F&2F at 50/60 Hz.

Reference handling

Source selection: IE n (internal, external TTL, external analog) vs SR830 FMOD i.

Frequency: OF. n (oscillator) and FRQ. (actual reference).

Phase & harmonic: REFP. (phase in degrees), REFN n (harmonic up to 65,535).

Advanced modes: Dual reference, dual harmonic, Virtual Reference™ (no physical reference), spectral display.

Inputs & outputs

Input modes: IMODE (A, A–B, current high‑bandwidth, current low‑noise) plus VMODE for voltage/current selection,
mapping SR830 ISRC.

Coupling & grounding: CP (AC/DC), FLOAT (float/ground shell).

Sensitivity: SEN n with mapping rules from SR830 SENS i depending on input mode.

Oscillator amplitude: OA. in V rms, extended down to
1

𝜇
V
.

Analog outputs: CH 1 n, CH 2 n for X%, Y%, etc; X., Y., MAG., PHA. for numeric readback.

Auxiliary I/O & buffers

DACs: DAC. n1 n2 (four outputs, 1 mV resolution).

ADCs: ADC. n (auxiliary voltages), plus transient recorder mode at up to 40 kSa/s.

Curve buffers: TD, TDC, TDT, DC. n, M, STR n for one‑shot, looping, triggered acquisition and storage rate control.

Built‑in experiments: frequency response sweeps, spectral display, transient recorder, harmonic analysis.

The manual emphasizes that “changing to the SIGNAL RECOVERY units allows the user to take advantage, maybe at a later
date, of the richer feature set of these instruments, including such items as the extended frequency range, dual
reference and harmonic modes, the transient recorder facility and the more powerful output data curve buffer.”

Interface & protocol: 7265 vs SR830
GPIB
No OUTX on 7265:

SR830: OUTX i selects which interface receives responses.

7265: always responds on the interface that received the command—your agent must not send OUTX.

Status byte differences:

SR830 serial poll bits: command in progress, data available, SRQ, etc.

7265 serial poll bits: bit 0 = command complete, bit 7 = data available and SRQ; other bits indicate invalid command,
parameter error, reference unlock, overload, new ADC values.

Your agent should always:

Send command (ibwrt or equivalent).

Serial poll (ST or ibrsp) until bit 0 (command complete) transitions.

If bit 7 (data available) is set, perform a read and parse the response.

Check error bits (invalid command, parameter error, overload, reference unlock) and surface them clearly.

Terminators:

7265 can use CR, CR/LF, or GPIB EOI as terminators; SR830 only CR or CR/LF.

Agent should configure the driver to match the existing lab convention (typically CR/LF).

RS232
Connector & role:

SR830: 25‑pin DCE.

7265: 9‑pin DTE; different cable wiring.

Handshake model:

SR830: CTS/DTR hardware or DRQ software handshaking.

7265: character‑by‑character echo handshake—send one character, wait for echo, then send the next.

Your agent must assume that any RS232 driver for the 7265 already implements this; if not, it must generate code that:

Loops over characters in the command string.

Writes one character.

Waits until the same character is read back before continuing.

Terminators & prompts:

Input terminator: CR or CR/LF.

Output terminator: CR/LF plus a prompt character: * (OK) or ? (error).

After each response, the agent should:

Strip terminators and prompt.

If prompt is ?, issue ST and N to diagnose the error and propagate a meaningful exception or log entry.

Multiple commands & delimiters
Command chaining: both instruments accept multiple commands separated by ; on one line.

Response delimiters:

SR830: comma‑separated.

7265: default comma, but user can change to any printable ASCII character.

Agent should not hard‑code commas; instead:

Either query or assume the delimiter from driver configuration.

Use robust splitting that can be parameterized.

Command model & SR830 mapping (what the agent must know)
Query semantics
SR830: CMD? for queries; parameters separated by commas.

7265: omit parameters to query; no commas between parameters.

For example:

SR830: FREQ? → reference frequency.

7265: FRQ. → reference frequency; OF. sets oscillator frequency.

Your agent should:

Treat SR830‑style CMD? as conceptual, not literal, when generating 7265 code.

Use the mapping table from the application note as a reference for translation.

Key mappings (illustrative, not exhaustive)
Identity & reset

SR830 \\*IDN? → 7265 ID (returns "7265").

SR830 \\*RST → 7265 ADF 1 (reset to defaults, but communication settings unchanged).

Status & errors

SR830 \\*STB? → 7265 ST.

SR830 \\*ESR?, \\*ERRS?, \\*LIAS? → 7265 ST, N, M (no direct equivalents; information is spread across status and
overload
bytes).

Auto functions

AGAN → ASEN (auto sensitivity/gain).

APHS → AQN (auto phase).

ARSV → AUTOMATIC 1 (automatic AC gain).

Input configuration

ICPL i → CP n (AC/DC).

IGND i → FLOAT n (float/ground).

ISRC variants → IMODE + VMODE.

Outputs & scaling

OUTP? 1/2/3/4 → X., Y., MAG., PHA..

OEXP (offset/expand) → XOF, YOF, EX.

Buffers & acquisition

STRT, SEND 0;STRT, SEND 1;STRT, TSTR 1;STRT → TD, TDC, TDT 0.

TRCA? → DC. n (curve data).

SPTS? → M (four values; points stored is the fourth).

Your agent should never assume that an SR830 command exists on the 7265; it must always translate via the mapping or
use native 7265 commands.

Integration patterns for stoner_measurement
Even without direct access to the repo, we can assume a typical Python measurement framework with:

Instrument driver classes.

SCPI‑like command methods.

Asynchronous or synchronous acquisition loops.

## 1. Driver abstraction

Your agent should generate a driver class along these lines:

Core responsibilities:

Connection management: GPIB or RS232, terminators, handshake.

Command send/receive: low‑level write, read, serial_poll primitives.

Status handling: ST, N, M parsing; raising structured exceptions.

High‑level methods: set_reference_source, set_frequency, set_phase, set_sensitivity, set_time_constant, read_XY,
read_Rtheta, start_curve, read_curve, configure_transient_recorder, etc.

Design choices for the agent:

Implement thin wrappers around the 7265 command set, using the mapping table as a guide.

Keep SR830 compatibility by providing a shim layer that exposes SR830‑style method names but internally calls 7265
commands.

## 2. Capability discovery & configuration

The agent should:

Provide methods to query current state using 7265 semantics (no parameters → query).

Implement mode‑safe configuration:

Ensure input mode, coupling, grounding, sensitivity, time constant, and reference are set coherently.

For advanced modes (dual reference, harmonic, spectral), expose explicit configuration methods rather than hidden
flags.

## 3. Timing & acquisition logic

The application note recommends a “rule of thumb” of five time constants before recording a new value at 12 dB/octave.

Your agent should:

Encapsulate this in helper methods, e.g. wait_for_settle() that:

Reads current time constant.

Computes
5
×
𝜏
.

Sleeps or schedules accordingly.

For curve buffers and transient recorder:

Provide start/stop methods that:

Issue TD, TDC, or TDT.

Poll status until acquisition completes or buffer fills.

Read data via DC. n and parse into arrays compatible with stoner_measurement.

## 4. Error‑aware coding patterns

The 7265 exposes rich error information via status and overload bytes. Your agent should:

After each command:

Poll status.

If error bits set (invalid command, parameter error, reference unlock, overload), call ST and N to get details.

Map these to Python exceptions or structured error objects.

For RS232:

Treat a ? prompt as an immediate error signal and follow the same diagnostic path.

Differences & similarities the agent should explicitly reason about
Similarities (safe to reuse SR830 mental models):

Dual‑phase lock‑in architecture (X, Y, R, θ).

Concept of internal/external reference, harmonics, time constants, filter slopes.

Multiple commands per line, comma‑separated responses (by default).

Auto functions (auto gain, auto phase, auto sensitivity).

Curve buffers and triggered acquisition.

Key differences (must be handled consciously):

Interface selection: no OUTX; 7265 always responds on the command interface.

Status model: different bit allocations; richer error reporting; agent must use serial poll as part of every write/read
routine.

RS232 handshake: character‑echo protocol and prompt characters; SR830‑style bulk writes will fail.

Query syntax: omit parameters instead of CMD?; no commas between parameters.

Extended capabilities: dual reference, dual harmonic, Virtual Reference, spectral display, transient recorder, more
powerful curve buffers.

## Programming guide for an LLM coding agent

Target: stoner_measurement Instrument Driver for the Signal Recovery 7265 DSP Lock‑in Amplifier

## 1. Mental Model: How the 7265 Works

The 7265 is a stateful DSP lock‑in with:

Dual‑phase detection (X, Y, R, θ)

Internal or external reference, including TTL and analog

Harmonic detection up to 65,535

Time constants from 10 µs to 100 ks

Transient recorder (40 kSa/s)

Curve buffers with triggered, looping, and one‑shot modes

Aux ADCs and DACs

Spectral display and Virtual Reference™

The agent should treat the instrument as a finite‑state machine with:

Input configuration state

Reference configuration state

Filter/time‑constant state

Output scaling state

Acquisition/buffer state

Every command modifies or queries one part of this state.

## 2. Interface Differences: 7265 vs SR830 (Critical for Code Generation)

### 2.1 No OUTX Command

SR830: OUTX i selects GPIB/RS232 output port.
7265: Always responds on the same interface that received the command.
→ The agent must never generate OUTX.

### 2.2 Query Syntax

SR830: CMD?
7265: CMD. with no parameters
Example:

SR830: FREQ?

7265: FRQ.

### 2.3 Parameter Separation

SR830: comma‑separated parameters
7265: parameters separated by spaces

### 2.4 Status Byte

The 7265 uses different bit assignments:

Bit 0 → command complete

Bit 7 → data available and SRQ

Other bits → invalid command, parameter error, reference unlock, overload

The agent must always serial‑poll after every command.

### 2.5 RS232 Handshake

7265 uses character‑echo handshake:

Send one character

Wait for the same character to be echoed

Continue

Also: responses end with CR/LF + prompt (* = OK, ? = error).

### 2.6 Response Delimiter

7265 allows any printable ASCII as delimiter.
Agent must not hard‑code commas.

## 3. Command Set Summary (LLM‑Friendly)

### 3.1 Reference & Oscillator

| Function             | SR830  | 7265    |
| -------------------- | ------ | ------- |
| Reference source     | FMOD i | IE n    |
| Oscillator frequency | FREQ f | OF. n   |
| Reference frequency  | FREQ?  | FRQ.    |
| Harmonic             | HARM i | REFN n  |
| Phase                | PHAS x | REFP. n |

### 3.2 Input Configuration

| Function   | SR830  | 7265         |
| ---------- | ------ | ------------ |
| Input mode | ISRC i | IMODE, VMODE |
| Coupling   | ICPL i | CP n         |
| Grounding  | IGND i | FLOAT n      |

### 3.3 Filters

| Function      | SR830  | 7265     |
| ------------- | ------ | -------- |
| Time constant | OFLT i | TC n     |
| Slope         | OFSL i | SLOPE n  |
| Line notch    | ILIN i | LF n1 n2 |

### 3.4 Outputs

| Function | SR830   | 7265 |
| -------- | ------- | ---- |
| X        | OUTP? 1 | X.   |
| Y        | OUTP? 2 | Y.   |
| R        | OUTP? 3 | MAG. |
| θ        | OUTP? 4 | PHA. |

### 3.5 Buffers & Acquisition

| Function              | SR830       | 7265          |
| --------------------- | ----------- | ------------- |
| Start acquisition     | STRT        | TD            |
| Loop acquisition      | SEND 1;STRT | TDC           |
| Triggered acquisition | TSTR 1;STRT | TDT 0         |
| Read buffer           | TRCA?       | DC. n         |
| Points in buffer      | SPTS?       | M (4th value) |

## 4. Behavioural Rules for the LLM Agent

### 4.1 After Every Command

Send command

Serial poll

If bit 7 set → read response

If prompt is ? → send ST and N

Raise structured error

### 4.2 When Changing Experimental Parameters

Wait 5 × time constant before reading outputs (rule of thumb from manual).

### 4.3 When Using RS232

Always generate character‑echo handshake code.

### 4.4 When Using Buffers

Use:

TD → one‑shot

TDC → continuous

TDT 0 → triggered

Then poll until complete.

## 5. Driver Skeleton for stoner_measurement

Below is a clean, idiomatic Python skeleton that fits the style of the repository (instrument class, SCPI‑like methods,
structured errors, numpy arrays for data).

This is not a full driver—just the scaffolding your agent will extend.

```python
import time
import numpy as np
from stoner.instrument import Instrument

class SR7265(Instrument):
    """Driver for the Signal Recovery 7265 DSP Lock-in Amplifier."""

    terminator = "\r\n"

    # ---------------------------
    # Low-level I/O
    # ---------------------------
    def write_cmd(self, cmd: str):
        """Send a command and perform mandatory serial-poll."""
        self.write(cmd + self.terminator)
        return self._poll_status()

    def read_response(self):
        """Read response and strip terminator + prompt."""
        resp = self.read().strip()
        if resp.endswith("*"):
            return resp[:-1].strip()
        if resp.endswith("?"):
            # Error: query status and overload bytes
            status = self.query("ST")
            overload = self.query("N")
            raise RuntimeError(f"7265 error: ST={status}, N={overload}")
        return resp

    def query(self, cmd: str):
        """Write command and read response."""
        self.write_cmd(cmd)
        return self.read_response()

    def _poll_status(self):
        """Serial poll: return status byte."""
        # stoner_measurement provides serial_poll() for GPIB instruments
        status = self.serial_poll()
        return status

    # ---------------------------
    # High-level configuration
    # ---------------------------
    def set_reference_source(self, mode: str):
        """mode: 'internal', 'ttl', 'analog'."""
        mapping = {
            "internal": 0,
            "ttl": 1,
            "analog": 2,
        }
        self.write_cmd(f"IE {mapping[mode]}")

    def set_frequency(self, freq_hz: float):
        self.write_cmd(f"OF. {freq_hz}")

    def get_frequency(self):
        return float(self.query("FRQ."))

    def set_phase(self, deg: float):
        self.write_cmd(f"REFP. {deg}")

    def set_harmonic(self, n: int):
        self.write_cmd(f"REFN {n}")

    # ---------------------------
    # Input configuration
    # ---------------------------
    def set_input_mode(self, mode: str):
        """mode: 'A', 'A-B', 'I-high', 'I-low'."""
        mapping = {
            "A": ("IMODE 0", "VMODE 1"),
            "A-B": ("IMODE 0", "VMODE 3"),
            "I-high": ("IMODE 1",),
            "I-low": ("IMODE 2",),
        }
        for cmd in mapping[mode]:
            self.write_cmd(cmd)

    def set_coupling(self, acdc: str):
        self.write_cmd(f"CP {0 if acdc=='AC' else 1}")

    def set_ground(self, float_or_ground: str):
        self.write_cmd(f"FLOAT {1 if float_or_ground=='float' else 0}")

    # ---------------------------
    # Filters
    # ---------------------------
    def set_time_constant(self, index: int):
        """index: 0–?? mapping to 10 µs → 100 ks."""
        self.write_cmd(f"TC {index}")

    def set_slope(self, db_per_oct: int):
        mapping = {6: 0, 12: 1, 18: 2, 24: 3}
        self.write_cmd(f"SLOPE {mapping[db_per_oct]}")

    # ---------------------------
    # Outputs
    # ---------------------------
    def read_x(self):
        return float(self.query("X."))

    def read_y(self):
        return float(self.query("Y."))

    def read_r(self):
        return float(self.query("MAG."))

    def read_theta(self):
        return float(self.query("PHA."))

    # ---------------------------
    # Acquisition / buffers
    # ---------------------------
    def start_one_shot(self):
        self.write_cmd("TD")

    def start_loop(self):
        self.write_cmd("TDC")

    def start_triggered(self):
        self.write_cmd("TDT 0")

    def read_curve(self, buffer=1):
        """Return numpy array of curve data."""
        raw = self.query(f"DC. {buffer}")
        # delimiter may not be comma; detect dynamically
        delim = "," if "," in raw else " "
        data = np.array([float(v) for v in raw.split(delim)])
        return data

    def buffer_points(self):
        """Return number of points stored."""
        m = self.query("M")
        parts = m.split(",")
        return int(parts[3])  # 4th value
```

## 6. How the LLM Agent Should Extend This Skeleton

Add capabilities:
DAC control (DAC. n1 n2)

ADC readback (ADC. n)

Automatic functions (ASEN, AQN, AUTOMATIC 1)

Synchronous time constant (SYNC n)

Expand/offset (XOF, YOF, EX)

Spectral display mode

Transient recorder (40 kSa/s)

Dual reference mode

Virtual Reference™

Add safety:
Structured exceptions for:

invalid command

parameter error

reference unlock

overload

Add timing helpers:

```python
def wait_for_settle(self):
    tc_index = int(self.query("TC"))
    tau = self._tc_index_to_seconds(tc_index)
    time.sleep(5 * tau)
```
