# Keithley 2400 Series SourceMeter Python/SCPI Programming Context for LLMs

This document is intended to be pasted into an LLM prompt as technical context for generating Python code that controls Keithley 2400-series SourceMeter instruments over GPIB, RS-232, USB-GPIB, or LAN-to-GPIB adapters. It is based on the Keithley **Series 2400 SourceMeter User’s Manual, document 2400S-900-01 Rev. K, September 2011**. The manual covers models in the 2400 family, including the 2400, 2400-LV, 2401, 2410, 2420, 2425, 2430, and 2440. Always check the exact model limits before generating source levels, ranges, pulse commands, or compliance values.

> Safety: the 2400 family can source hazardous voltage and current. Generated code must default the output OFF, set conservative compliance limits before enabling output, and turn output OFF in `finally` blocks. The manual warns that shock hazards may exist above 30 V RMS, 42.4 V peak, or 60 VDC, and the terminals are for Category I/II style measurement/control connections rather than arbitrary mains connections.

---

## 1. Instrument model and programming assumptions

The Keithley 2400 is a SourceMeter: it can source voltage while measuring current, source current while measuring voltage, measure resistance, and optionally measure multiple quantities in one reading. Its SCPI interface is hierarchical and uses commands such as `:SOURce:VOLTage:LEVel`, `:SENSe:CURRent:PROTection`, `:READ?`, `:TRACe:DATA?`, and `:STATus:OPERation:CONDition?`.

Recommended Python stack:

```python
import pyvisa

rm = pyvisa.ResourceManager()
smu = rm.open_resource("GPIB0::24::INSTR")
smu.timeout = 20000
smu.write_termination = "\n"
smu.read_termination = "\n"
print(smu.query("*IDN?"))
```

Use `write()` for SCPI commands, `query()` for commands ending in `?`, and avoid `query()` after non-query commands. Most code should issue `*RST`, `*CLS`, configure source, configure sense, configure format, then either use direct `:READ?`/`:FETCh?` or buffered `:INIT`/`:TRACe:DATA?` acquisition.

---

## 2. Command conventions

Keithley SCPI commands are case-insensitive. Uppercase letters indicate the short form; lowercase letters are optional. For example:

```text
:SOURce:VOLTage:LEVel 1.0
:SOUR:VOLT:LEV 1.0
```

Both forms are equivalent. Prefer short forms in generated Python for compactness, but prefer long forms in explanations.

Important common commands:

```text
*IDN?       # identify instrument
*RST        # reset to default state
*CLS        # clear status/event/error registers
*OPC?       # query operation complete; blocks until prior operations complete
*TRG        # bus trigger if trigger source is BUS
*SRE <n>    # service request enable register
*ESE <n>    # standard event status enable register
*ESR?       # read and clear standard event status register
*STB?       # read status byte
```

---

## 3. Safe initialization template

Use this pattern before any measurement routine:

```python
def initialize_2400(smu):
    smu.write("*RST")
    smu.write("*CLS")
    smu.write(":OUTP OFF")
    smu.write(":SYST:AZER ON")          # if supported by firmware/model
    smu.write(":FORM:ELEM VOLT,CURR,RES,TIME,STAT")
    smu.write(":SYST:TIME:RES")         # reset absolute timestamp
    smu.write(":TRAC:CLE")              # clear buffer
```

Always set a compliance limit before turning output on. Example: when sourcing voltage, set current compliance with `:SENS:CURR:PROT <amps>`. When sourcing current, set voltage compliance with `:SENS:VOLT:PROT <volts>`.

---

## 4. Source subsystem

The source subsystem configures what the SMU drives into the DUT.

### 4.1 Select source function

```text
:SOUR:FUNC VOLT      # source voltage
:SOUR:FUNC CURR      # source current
:SOUR:FUNC MEM       # memory sweep mode
```

### 4.2 Voltage source commands

```text
:SOUR:VOLT:MODE FIX       # fixed source level
:SOUR:VOLT:LEV <V>        # source voltage level
:SOUR:VOLT:RANG <V>       # manual source voltage range
:SOUR:VOLT:RANG:AUTO ON   # source autorange
:SOUR:VOLT:PROT <A>       # current compliance alias may vary; prefer SENS:CURR:PROT
:SOUR:DEL <seconds>       # source settling delay before measurement
:SOUR:DEL:AUTO ON|OFF     # auto delay
```

When generating code, prefer this safer idiom:

```text
:SOUR:FUNC VOLT
:SOUR:VOLT:MODE FIX
:SOUR:VOLT:RANG:AUTO ON
:SOUR:VOLT:LEV 0
:SENS:CURR:PROT 0.01
:OUTP ON
:SOUR:VOLT:LEV 1.0
```

### 4.3 Current source commands

```text
:SOUR:FUNC CURR
:SOUR:CURR:MODE FIX
:SOUR:CURR:LEV <A>
:SOUR:CURR:RANG <A>
:SOUR:CURR:RANG:AUTO ON|OFF
:SENS:VOLT:PROT <V>
```

### 4.4 Output subsystem

```text
:OUTP ON
:OUTP OFF
:OUTP:SMOD NORM|HIMP|ZERO|GUAR   # output-off state on models/firmware that support it
:SOUR:CLE:AUTO ON|OFF            # source auto-clear after each SDM cycle
```

A robust Python driver should have a `safe_output_off()` method that catches communication errors but attempts `:OUTP OFF`.

---

## 5. Sense subsystem

The sense subsystem configures what the SMU measures.

### 5.1 Enable measurement functions

```text
:SENS:FUNC "VOLT"           # measure voltage only
:SENS:FUNC "CURR"           # measure current only
:SENS:FUNC "RES"            # measure resistance only
:SENS:FUNC:CONC ON|OFF      # concurrent measurements where supported
:SENS:FUNC:ON "VOLT","CURR"
:SENS:FUNC:OFF "RES"
:SENS:FUNC:STAT? "CURR"
```

Notes:

- If sourcing voltage, normally measure current; optionally also measure voltage and resistance.
- If sourcing current, normally measure voltage.
- Resistance can be measured directly or computed from V/I depending on mode.

### 5.2 Ranges and autorange

```text
:SENS:CURR:RANG <A>
:SENS:CURR:RANG:AUTO ON|OFF
:SENS:VOLT:RANG <V>
:SENS:VOLT:RANG:AUTO ON|OFF
:SENS:RES:RANG <ohms>
:SENS:RES:RANG:AUTO ON|OFF
```

For speed and determinism, generated code should use fixed ranges. For convenience and unknown DUTs, use autorange with conservative compliance.

### 5.3 Compliance/protection

```text
:SENS:CURR:PROT <A>      # current compliance while sourcing voltage
:SENS:VOLT:PROT <V>      # voltage compliance while sourcing current
:SENS:CURR:PROT?         # query current compliance
:SENS:VOLT:PROT?         # query voltage compliance
```

Compliance is not an error; it is a limiting state. Code should parse the status field returned by `:READ?`/`:FETCh?` or query status registers when compliance matters.

### 5.4 Integration time, filtering, and autozero

```text
:SENS:CURR:NPLC <n>
:SENS:VOLT:NPLC <n>
:SENS:RES:NPLC <n>
:SENS:AVER:STAT ON|OFF
:SENS:AVER:COUN <n>       # 1 to 100
:SENS:AVER:TCON REP|MOV   # repeat or moving average, where supported
:SYST:AZER ON|OFF
```

Guidance:

- Higher NPLC gives lower noise and lower speed.
- Lower NPLC gives faster measurements and more noise.
- Autozero improves long-term accuracy but reduces speed.
- Filtering improves stability but changes timing and latency.

---

## 6. Data format and parsing

The `:FORMat` subsystem controls returned data. The most useful command for Python is:

```text
:FORM:ELEM VOLT,CURR,RES,TIME,STAT
```

Common elements:

```text
VOLT   measured voltage
CURR   measured current
RES    measured resistance
TIME   timestamp
STAT   reading status word
```

Use ASCII format unless speed requires binary transfer:

```text
:FORM:DATA ASC
```

A typical response after `:READ?` or `:TRAC:DATA?` is a comma-separated flat list. If five elements are selected and N readings are returned, reshape into rows of five:

```python
def parse_readings(csv_text, elements=("VOLT", "CURR", "RES", "TIME", "STAT")):
    values = [float(x) for x in csv_text.strip().split(",") if x.strip()]
    width = len(elements)
    if len(values) % width:
        raise ValueError(f"Expected multiples of {width}, got {len(values)} values")
    return [dict(zip(elements, values[i:i+width])) for i in range(0, len(values), width)]
```

---

## 7. Measurement commands and data flow

The core read commands are:

```text
:MEAS?       # configure, initiate, and fetch according to function shortcut
:READ?       # initiate trigger model and fetch data
:INIT        # initiate trigger model; returns immediately unless followed by wait/query
:FETC?       # fetch latest completed reading/readings
:SENS:DATA?  # latest sense data; similar to FETCh? in relevant contexts
```

Important distinction:

- `:READ?` triggers a measurement sequence and returns data.
- `:INIT` starts the trigger model without immediately reading data.
- `:FETC?` retrieves completed data.
- `:TRAC:DATA?` retrieves data stored in the reading buffer.

For one reading, generate simple code using `:READ?`. For sweeps, external triggering, high count acquisition, statistics, or repeatable timing, use `:TRACe` and trigger/arm configuration.

---

## 8. Reading buffer / TRACe subsystem

The 2400 has a data store controlled by `:TRACe` or synonym `:DATA`. The manual states that this subsystem configures and controls storage of readings into the buffer, `:TRACe:DATA?` returns all readings in the data store, and returned format is controlled by `:FORMat`.

### 8.1 Essential buffer commands

```text
:TRAC:CLE                  # clear buffer
:TRAC:FREE?                # returns available bytes,reserved bytes
:TRAC:POIN <n>             # buffer size, 1 to 2500, default 100
:TRAC:POIN?                # programmed buffer size
:TRAC:POIN:ACT?            # actual number of stored readings
:TRAC:FEED SENS            # store raw sense readings
:TRAC:FEED CALC            # store CALC1 readings
:TRAC:FEED CALC2           # store CALC2 readings
:TRAC:FEED:CONT NEXT       # start storing, then stop when full
:TRAC:FEED:CONT NEV        # disable buffer feed
:TRAC:DATA?                # read stored data
```

Buffer size is 1 to 2500 readings. `:TRACe:FEED` selects whether raw sense readings or calculated values are stored. `:TRACe:FEED` cannot be changed while buffer storage is active.

### 8.2 Buffered acquisition template

```python
def acquire_buffered(smu, n):
    smu.write(":OUTP OFF")
    smu.write(":TRAC:CLE")
    smu.write(f":TRAC:POIN {n}")
    smu.write(":TRAC:FEED SENS")
    smu.write(":TRAC:FEED:CONT NEXT")
    smu.write(f":TRIG:COUN {n}")
    smu.write(":ARM:COUN 1")
    smu.write(":OUTP ON")
    smu.write(":INIT")
    smu.query("*OPC?")
    data = smu.query(":TRAC:DATA?")
    smu.write(":OUTP OFF")
    return data
```

### 8.3 Buffer statistics

The buffer can be used with `CALCulate3` statistics for minimum, maximum, peak-to-peak, mean, and standard deviation. Use this when the instrument should compute aggregate statistics rather than transferring all readings. Configure the buffer feed first, acquire readings, then query the relevant calculation/statistic command.

---

## 9. Trigger and arm model

The 2400 trigger model has an idle layer, an arm layer, and a trigger layer. The trigger layer performs the Source-Delay-Measure cycle. The manual describes trigger delay as a user-programmable delay after a trigger event and before device action; the SDM cycle can produce output trigger events after source, delay, or measurement.

### 9.1 Counts

```text
:ARM:COUN <n|INF>       # number of arm-layer passes
:TRIG:COUN <n|INF>      # number of trigger-layer actions per arm
```

Typical settings:

```text
:ARM:COUN 1
:TRIG:COUN 1       # one reading
:TRIG:COUN 100     # 100 readings in one arm pass
```

Use `ARM:COUN INF` only for advanced continuous tests where an external condition, abort, output-enable line, or controller logic will stop acquisition.

### 9.2 Trigger and arm event sources

```text
:ARM:SOUR IMM       # arm immediately
:ARM:SOUR TIM       # arm by timer
:ARM:SOUR MAN       # front-panel TRIG key
:ARM:SOUR BUS       # GET or *TRG bus event
:ARM:SOUR TLIN      # Trigger Link
:ARM:SOUR NST       # low start-of-test pulse on Digital I/O
:ARM:SOUR PST       # high start-of-test pulse on Digital I/O
:ARM:SOUR BST       # high or low SOT pulse

:TRIG:SOUR IMM      # trigger immediately
:TRIG:SOUR TLIN     # Trigger Link trigger event
```

Only `IMMediate` and `TLINk` are available as trigger-layer control sources on the 2400. Other event sources apply to the arm layer.

### 9.3 Trigger delay and arm timer

```text
:TRIG:DEL <seconds>       # 0 to 999.9999 s
:ARM:TIM <seconds>        # timer interval for arm layer when ARM:SOUR TIM
```

`TRIG:DEL` delays trigger-layer operation after the programmed trigger event occurs. For Model 2430 pulse mode, trigger delay is not used; pulse width and pulse delay control pulse timing.

### 9.4 Bypass direction

```text
:ARM:TCON:DIR SOUR|ACC
:TRIG:TCON:DIR SOUR|ACC
```

`SOURce` enables control-source bypass on the first pass through the layer. `ACCeptor` disables bypass and waits for the selected event even on the first pass.

### 9.5 Trigger Link input/output lines

```text
:ARM:TCON:ILIN <n>
:TRIG:TCON:ILIN <n>
:ARM:TCON:OLIN <n>
:TRIG:TCON:OLIN <n>
:ARM:TCON:OUTP TENT|TEX|NONE
:TRIG:TCON:OUTP SOUR,DEL,SENS|NONE
```

Trigger-layer output events can be generated after source level is set, after the delay period, or after measurement. This is useful for synchronizing multiple SMUs, counters, switching systems, or handlers.

---

## 10. Common measurement recipes

### 10.1 Source voltage, measure current

```python
def source_voltage_measure_current(smu, voltage, current_compliance=0.01, nplc=1.0):
    smu.write("*CLS")
    smu.write(":OUTP OFF")
    smu.write(":SOUR:FUNC VOLT")
    smu.write(":SOUR:VOLT:MODE FIX")
    smu.write(":SOUR:VOLT:RANG:AUTO ON")
    smu.write(":SOUR:VOLT:LEV 0")
    smu.write(f":SENS:CURR:PROT {current_compliance}")
    smu.write(":SENS:FUNC \"CURR\"")
    smu.write(":SENS:CURR:RANG:AUTO ON")
    smu.write(f":SENS:CURR:NPLC {nplc}")
    smu.write(":FORM:ELEM VOLT,CURR,TIME,STAT")
    try:
        smu.write(":OUTP ON")
        smu.write(f":SOUR:VOLT:LEV {voltage}")
        return smu.query(":READ?")
    finally:
        smu.write(":OUTP OFF")
```

### 10.2 Source current, measure voltage

```python
def source_current_measure_voltage(smu, current, voltage_compliance=10, nplc=1.0):
    smu.write("*CLS")
    smu.write(":OUTP OFF")
    smu.write(":SOUR:FUNC CURR")
    smu.write(":SOUR:CURR:MODE FIX")
    smu.write(":SOUR:CURR:RANG:AUTO ON")
    smu.write(":SOUR:CURR:LEV 0")
    smu.write(f":SENS:VOLT:PROT {voltage_compliance}")
    smu.write(":SENS:FUNC \"VOLT\"")
    smu.write(":SENS:VOLT:RANG:AUTO ON")
    smu.write(f":SENS:VOLT:NPLC {nplc}")
    smu.write(":FORM:ELEM VOLT,CURR,TIME,STAT")
    try:
        smu.write(":OUTP ON")
        smu.write(f":SOUR:CURR:LEV {current}")
        return smu.query(":READ?")
    finally:
        smu.write(":OUTP OFF")
```

### 10.3 I-V sweep using host loop

Use a host loop when you want simple, explicit Python control:

```python
def iv_sweep_host_loop(smu, voltages, current_compliance=0.01, delay=0.05):
    smu.write("*CLS")
    smu.write(":OUTP OFF")
    smu.write(":SOUR:FUNC VOLT")
    smu.write(":SOUR:VOLT:MODE FIX")
    smu.write(f":SENS:CURR:PROT {current_compliance}")
    smu.write(":SENS:FUNC \"CURR\"")
    smu.write(":FORM:ELEM VOLT,CURR,TIME,STAT")
    rows = []
    try:
        smu.write(":OUTP ON")
        for v in voltages:
            smu.write(f":SOUR:VOLT:LEV {v}")
            if delay:
                import time; time.sleep(delay)
            rows.append(smu.query(":READ?").strip())
    finally:
        smu.write(":SOUR:VOLT:LEV 0")
        smu.write(":OUTP OFF")
    return rows
```

### 10.4 Internal linear staircase sweep

Use the instrument sweep engine for better timing and lower bus overhead:

```text
:SOUR:FUNC VOLT
:SOUR:VOLT:MODE SWE
:SOUR:SWE:RANG AUTO
:SOUR:VOLT:STAR <start_v>
:SOUR:VOLT:STOP <stop_v>
:SOUR:VOLT:STEP <step_v>
:SOUR:SWE:SPAC LIN
:SOUR:SWE:POIN <points>
:SENS:CURR:PROT <amps>
:TRAC:CLE
:TRAC:POIN <points>
:TRAC:FEED SENS
:TRAC:FEED:CONT NEXT
:TRIG:COUN <points>
:ARM:COUN 1
:OUTP ON
:INIT
*OPC?
:TRAC:DATA?
:OUTP OFF
```

Variants:

```text
:SOUR:SWE:SPAC LOG       # logarithmic staircase sweep
:SOUR:LIST:VOLT <list>   # custom/list sweep, command spelling may vary by source function
```

### 10.5 Resistance measurements

For 2-wire resistance:

```text
:SOUR:FUNC CURR
:SENS:FUNC "RES"
:SENS:RES:MODE MAN|AUTO    # mode details vary by model/firmware
:SENS:RES:RANG:AUTO ON
:READ?
```

For 4-wire/remote sense, enable remote sensing before measurement:

```text
:SYST:RSEN ON       # remote sense / 4-wire sensing
:SYST:RSEN OFF      # local sense / 2-wire sensing
```

---

## 11. Pulse mode caveat for Model 2430

The Model 2430 has pulse-mode-specific behavior. In pulse mode, several normal DC-mode commands are ignored or invalid. The manual notes that concurrent measurements are always disabled in 2430 pulse mode, and trigger delay is not used; pulse timing uses pulse width and pulse delay. Generated code must check `*IDN?` and avoid using generic DC sweep assumptions for 2430 pulse measurements.

---

## 12. Digital I/O, limit tests, and handlers

The digital I/O port supports handler-style testing and simple digital output control. Digital output lines can be controlled with:

```text
:SOUR2:TTL <decimal_pattern>
:SOUR2:TTL?
```

The 4-bit output value maps to OUT1–OUT4; values 0–15 represent low/high patterns. With the optional Model 2499-DIGIO adapter, the digital I/O port can expand to 16 bits. Output lines can be used for handlers, external relays, or indicators, but current limits and external protection must be respected.

Limit testing uses the `CALCulate` subsystem and can report pass/fail states. To know which specific upper/lower limit failed, read the Measurement Event Register rather than relying only on a simple pass/fail query.

---

## 13. Status structure and error handling

The status subsystem controls and reads the SourceMeter status registers. The manual identifies Measurement, Questionable, and Operation event/condition registers. Event queries report latched events and generally clear the queried event register; condition queries report current live condition bits.

### 13.1 Essential status commands

```text
:STAT:MEAS:EVEN?       # read Measurement Event Register
:STAT:QUES:EVEN?       # read Questionable Event Register
:STAT:OPER:EVEN?       # read Operation Event Register
:STAT:MEAS:COND?       # read live Measurement condition register
:STAT:QUES:COND?       # read live Questionable condition register
:STAT:OPER:COND?       # read live Operation condition register
:STAT:MEAS:ENAB <n>    # enable measurement events
:STAT:QUES:ENAB <n>    # enable questionable events
:STAT:OPER:ENAB <n>    # enable operation events
:STAT:PRES             # return status event registers to default conditions
```

### 13.2 Error queue

```text
:SYST:ERR?             # read oldest error/status message
:SYST:ERR:ALL?         # read all errors, where supported
:SYST:ERR:COUN?        # count errors, where supported
:STAT:QUE?             # same function as SYST:ERR? on this family
:STAT:QUE:CLE          # clear error queue
```

The error queue is FIFO and can hold up to 10 messages. A robust Python wrapper should call `:SYST:ERR?` after configuration blocks and repeatedly drain until `0,"No error"` or equivalent.

```python
def drain_errors(smu, max_reads=20):
    errors = []
    for _ in range(max_reads):
        msg = smu.query(":SYST:ERR?").strip()
        errors.append(msg)
        if msg.startswith("0"):
            break
    return errors
```

### 13.3 Service request pattern

For advanced code, configure status enable registers and SRQ so the controller can wait for completion or error instead of polling. Simpler Python code should use `*OPC?`, adequate timeouts, and explicit error-queue reads.

---

## 14. Timing model and performance

Measurement timing is affected by:

- NPLC integration time.
- Autozero state.
- Source delay and trigger delay.
- Autoranging and range-change mode.
- Filter count and filter type.
- Bus transfer format, especially ASCII vs binary.
- Buffering vs immediate bus reads.

Useful timing-related commands:

```text
:SOUR:DEL <seconds>
:SOUR:DEL:AUTO ON|OFF
:TRIG:DEL <seconds>
:SYST:TIME:RES
:SYST:TIME:RES:AUTO ON|OFF
:SYST:RCM SING|MULT
```

The manual distinguishes source delay, trigger delay, source configuration time, A/D conversion time, and firmware overhead. For deterministic sweeps, use fixed ranges, fixed NPLC, autozero off if acceptable, filter off, and the trace buffer.

---

## 15. Recommended Python driver surface

When asking an LLM to generate code, prefer a small driver class with these methods:

```python
class Keithley2400:
    def __init__(self, resource_name: str, timeout_ms: int = 20000): ...
    def close(self): ...
    def reset(self): ...
    def identify(self) -> str: ...
    def check_errors(self) -> list[str]: ...
    def output(self, on: bool): ...
    def configure_source_voltage(self, level=0.0, compliance=0.01, autorange=True): ...
    def configure_source_current(self, level=0.0, compliance=10.0, autorange=True): ...
    def configure_measure_current(self, nplc=1.0, autorange=True): ...
    def configure_measure_voltage(self, nplc=1.0, autorange=True): ...
    def read_once(self) -> dict: ...
    def voltage_sweep(self, start, stop, points, compliance, nplc=1.0): ...
    def current_sweep(self, start, stop, points, compliance, nplc=1.0): ...
    def configure_buffer(self, points, elements=("VOLT", "CURR", "RES", "TIME", "STAT")): ...
    def fetch_buffer(self) -> list[dict]: ...
```

Critical implementation details:

- Always call `:OUTP OFF` before reconfiguring source mode.
- Always set source level to zero before enabling output unless the user explicitly requests otherwise.
- Always set compliance before output on.
- Use `try/finally` to turn output off.
- Do not assume returned element order; set `:FORM:ELEM` explicitly.
- After errors or timeouts, attempt `:ABOR` then `:OUTP OFF` then drain errors.
- Use `*OPC?` after `:INIT` for buffered operations.

---

## 16. Minimal full example: buffered voltage sweep

```python
import numpy as np
import pyvisa

ELEMENTS = ("VOLT", "CURR", "RES", "TIME", "STAT")

def parse_readings(text, elements=ELEMENTS):
    vals = [float(x) for x in text.strip().split(",") if x.strip()]
    width = len(elements)
    if len(vals) % width:
        raise ValueError(f"Bad reading count: {len(vals)} values for width {width}")
    return [dict(zip(elements, vals[i:i+width])) for i in range(0, len(vals), width)]

def run_voltage_sweep(resource="GPIB0::24::INSTR", start=-1, stop=1, points=101,
                      current_compliance=0.01, nplc=1.0):
    rm = pyvisa.ResourceManager()
    smu = rm.open_resource(resource)
    smu.timeout = 60000
    smu.write_termination = "\n"
    smu.read_termination = "\n"

    try:
        smu.write("*RST")
        smu.write("*CLS")
        smu.write(":OUTP OFF")
        smu.write(":SOUR:FUNC VOLT")
        smu.write(":SOUR:VOLT:MODE FIX")
        smu.write(":SOUR:VOLT:RANG:AUTO ON")
        smu.write(":SOUR:VOLT:LEV 0")
        smu.write(f":SENS:CURR:PROT {current_compliance}")
        smu.write(":SENS:FUNC \"CURR\"")
        smu.write(":SENS:CURR:RANG:AUTO ON")
        smu.write(f":SENS:CURR:NPLC {nplc}")
        smu.write(":FORM:DATA ASC")
        smu.write(":FORM:ELEM VOLT,CURR,RES,TIME,STAT")

        readings = []
        smu.write(":OUTP ON")
        for v in np.linspace(start, stop, points):
            smu.write(f":SOUR:VOLT:LEV {v:.12g}")
            readings.extend(parse_readings(smu.query(":READ?")))
        smu.write(":SOUR:VOLT:LEV 0")
        return readings
    finally:
        try:
            smu.write(":OUTP OFF")
        finally:
            smu.close()
            rm.close()
```

---

## 17. SCPI quick reference by task

### Identification and reset

```text
*IDN?
*RST
*CLS
:SYST:ERR?
```

### Output safety

```text
:OUTP OFF
:OUTP ON
:SOUR:VOLT:LEV 0
:SOUR:CURR:LEV 0
```

### Source voltage

```text
:SOUR:FUNC VOLT
:SOUR:VOLT:MODE FIX
:SOUR:VOLT:LEV <V>
:SOUR:VOLT:RANG:AUTO ON|OFF
:SOUR:VOLT:RANG <V>
:SENS:CURR:PROT <A>
```

### Source current

```text
:SOUR:FUNC CURR
:SOUR:CURR:MODE FIX
:SOUR:CURR:LEV <A>
:SOUR:CURR:RANG:AUTO ON|OFF
:SOUR:CURR:RANG <A>
:SENS:VOLT:PROT <V>
```

### Measure voltage/current/resistance

```text
:SENS:FUNC "VOLT"
:SENS:FUNC "CURR"
:SENS:FUNC "RES"
:SENS:VOLT:NPLC <n>
:SENS:CURR:NPLC <n>
:SENS:RES:NPLC <n>
:SENS:AVER:STAT ON|OFF
:SENS:AVER:COUN <n>
```

### Read data

```text
:FORM:DATA ASC
:FORM:ELEM VOLT,CURR,RES,TIME,STAT
:READ?
:INIT
*OPC?
:FETC?
:SENS:DATA?
```

### Buffer

```text
:TRAC:CLE
:TRAC:POIN <1..2500>
:TRAC:POIN:ACT?
:TRAC:FEED SENS|CALC|CALC2
:TRAC:FEED:CONT NEXT|NEV
:TRAC:DATA?
```

### Trigger/arm

```text
:ARM:COUN <n|INF>
:TRIG:COUN <n|INF>
:ARM:SOUR IMM|TIM|MAN|BUS|TLIN|NST|PST|BST
:TRIG:SOUR IMM|TLIN
:TRIG:DEL <seconds>
:ARM:TIM <seconds>
:ARM:TCON:DIR SOUR|ACC
:TRIG:TCON:DIR SOUR|ACC
:TRIG:TCON:OUTP SOUR,DEL,SENS|NONE
```

### Status and errors

```text
:STAT:PRES
:STAT:MEAS:EVEN?
:STAT:QUES:EVEN?
:STAT:OPER:EVEN?
:STAT:MEAS:COND?
:STAT:QUES:COND?
:STAT:OPER:COND?
:STAT:MEAS:ENAB <n>
:STAT:QUES:ENAB <n>
:STAT:OPER:ENAB <n>
:SYST:ERR?
:STAT:QUE?
:STAT:QUE:CLE
```

---

## 18. LLM code-generation constraints

When this document is used as prompt context, generated code must:

1. Ask for or expose the VISA resource name.
2. Query `*IDN?` and optionally validate that it contains Keithley and a 2400-series model.
3. Turn output off before configuration.
4. Set compliance limits before output on.
5. Use explicit `:FORM:ELEM` and parse accordingly.
6. Turn output off in `finally`.
7. Include error draining with `:SYST:ERR?`.
8. Use `*OPC?` for triggered/buffered operations.
9. Avoid model-specific pulse features unless `*IDN?` confirms Model 2430 or the user explicitly asks.
10. Never silently exceed instrument model voltage, current, or power limits.

---

## Source notes

Key manual facts used here:

- The SourceMeter family supports source-measure operations across model-dependent voltage/current ranges and compliance limits.
- The `TRACe` subsystem controls data storage into the reading buffer, with buffer sizes from 1 to 2500 readings and feed sources such as raw `SENSe` or calculated readings.
- The `STATus` subsystem exposes Measurement, Questionable, and Operation event/condition registers and an error queue.
- The trigger/arm model uses arm count, trigger count, event sources, delays, bypass direction, and trigger-link input/output events; the trigger-layer device action is the Source-Delay-Measure cycle.
