# Lake Shore Model 625 Remote Programming Notes

## Overview

The Lake Shore Model 625 uses a proprietary ASCII command language rather than SCPI, although it adopts many
IEEE-488.2 common commands (e.g. `*IDN?`, `*RST`, `*CLS`, `*STB?`). The same command set is available over both:

* IEEE-488 (GPIB)
* RS-232 serial

Consequently, software written for one interface generally works unchanged on the other apart from the communications
layer.

---

## Communication

### Interfaces

#### GPIB

* IEEE-488.2 compliant
* Supports remote/local operation
* Supports SRQ (Service Request)

#### Serial

* RS-232C
* 9600, 19200, 38400 or 57600 baud
* ASCII messages
* Up to ~10 readings/s

---

## Command syntax

Commands are simple ASCII keywords.

Examples:

```text
RATE 0.500
SETI 10
PSH 1
```

Queries append a question mark:

```text
RATE?
RDGI?
PSH?
```

Multiple commands may be sent in one message using semicolons:

```text
RATE 0.5;RATE?
```

Responses are terminated by the interface terminator (CR/LF depending on interface configuration). Commands are
case-insensitive. Correct spelling and spacing are important; invalid commands are simply ignored rather than
generating syntax errors.

---

## IEEE-488.2 Common Commands

The instrument supports the standard IEEE-488.2 commands expected by VISA software.

| Command          | Purpose                      |
| ---------------- | ---------------------------- |
| `*CLS`           | Clear status registers       |
| `*ESE` / `*ESE?` | Event Status Enable          |
| `*ESR?`          | Event Status Register        |
| `*IDN?`          | Instrument identification    |
| `*OPC` / `*OPC?` | Operation complete           |
| `*RST`           | Reset instrument             |
| `*SRE` / `*SRE?` | Service Request Enable       |
| `*STB?`          | Status Byte                  |
| `*TRG`           | Software trigger             |
| `*TST?`          | Self test                    |
| `*WAI`           | Wait for previous operations |

These make the instrument straightforward to integrate with PyVISA or LabVIEW.

---

## Instrument-specific commands

The proprietary commands fall into several logical groups.

### Configuration

* `BAUD`
* `IEEE`
* `MODE`
* `DISP`
* `LOCK`
* `DFLT`

These configure communications, display behaviour and keypad locking.

---

### Output programming

Commands controlling the magnet current include:

* current setpoint
* ramp rate
* compliance voltage
* ramp segments
* current limits
* triggering

Representative commands include:

```text
RATE
RATE?
LIMIT
LIMIT?
RSEG
RSEGS
```

---

### Persistent switch heater

Dedicated commands control the persistent switch heater independently of the magnet current.

Examples:

```text
PSH
PSH?
PSHS
PSHS?
PSHIS?
```

These configure:

* heater on/off
* heater current
* heater delay
* persistent-mode behaviour

---

### Quench protection

Commands configure internal quench detection:

```text
QNCH
QNCH?
```

These include enabling/disabling detection and configuring the current-step threshold.

---

### Field conversion

The instrument can display and report magnetic field rather than current using a stored calibration constant.

Commands:

```text
FLDS
FLDS?
```

---

### Measurement queries

The instrument provides readback commands for all important outputs.

| Query    | Returns              |
| -------- | -------------------- |
| `RDGI?`  | Output current       |
| `RDGF?`  | Magnetic field       |
| `RDGV?`  | Output voltage       |
| `RDGRV?` | Remote-sense voltage |

These are the commands most commonly used during automated experiments.

---

## Status system

The Model 625 implements a structured status model similar to other IEEE-488 instruments.

It contains:

* Standard Event Status Register
* Operation Status Register
* Error Status Register
* Hardware Error Register
* Operational Error Register
* Persistent Switch Heater Error Register
* Status Byte Register
* Service Request (SRQ)

Dedicated commands allow:

```text
ERST?
ERSTR?
ERSTE

OPST?
OPSTR?
OPSTE
```

This allows software to poll or receive asynchronous notification of faults instead of repeatedly querying instrument
state.

---

## Typical remote control workflow

A typical automation sequence would be:

```text
*RST
*CLS

Configure communication
Configure limits
Configure compliance voltage
Configure ramp rate
Configure field constant
Configure quench detection

Set desired current

Trigger ramp

Poll

RDGI?
RDGV?

Wait for completion

Enable/disable persistent switch if required

Return output to zero
```

---

## Programming model

Unlike many laboratory instruments, the Model 625 does **not** use a hierarchical SCPI syntax such as:

```text
:SOUR:CURR
:MEAS:VOLT?
```

Instead it uses a flat command namespace:

```text
RATE
PSH
QNCH
RDGI?
LIMIT
```

This makes the interface compact and easy to parse, but requires software to know the proprietary command names.

---

### Suitability for Python

The interface is well suited to `pyvisa`:

```python
ps.write("*CLS")
ps.write("RATE 0.100")
ps.write("SETI 5.000")
ps.write("*TRG")

current = float(ps.query("RDGI?"))
voltage = float(ps.query("RDGV?"))
```

The combination of IEEE-488.2 common commands, simple ASCII syntax, and dedicated readback commands makes the Model
625 relatively straightforward to automate despite its non-SCPI command set.

If your goal is similar to the Keithley document we created previously, I can also produce a **comprehensive
LLM-oriented Markdown programming guide** for the Model 625, covering every command, the status architecture, safe
operating sequences (including persistent switch handling), and Python programming patterns.
