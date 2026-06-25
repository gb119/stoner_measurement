# Magnet Power Supply Command Cross-Reference

Below is a **strict command‑by‑command cross‑reference table** between:

* ✅ **Lake Shore 625 (LS625)** — Chapter 5
* ✅ **Oxford Instruments IPS120** — Chapter 8
* ✅ **Oxford Mercury IPS** — Chapter 7

This is organised as a **true mapping table**:

* Row = *one concrete command*
* Columns show:
  * Equivalent command(s)
  * Or **“—” if no direct equivalent**
  * Notes for semantic differences

***

## 📘 Full Command Cross‑Reference Table

### 🧲 1. Setpoint / Target Commands

| Function                  | Lake Shore 625  | IPS120   | Mercury IPS           | Notes                           |
| ------------------------- | --------------- | -------- | --------------------- | ------------------------------- |
| Set current               | `SETI <val>`    | `I<val>` | `SET:...:CURR <val>`  | Same function                   |
| Read current (measured)   | `RDGI?`         | `R1`     | `READ:...:CURR?`      | IPS120 uses register            |
| Read setpoint             | `SETI?`         | `R0`     | `READ:...:CURR?`      | Mercury same signal used        |
| Set field (if calibrated) | via calibration | implicit | `SET:...:FIELD <val>` | Mercury has native field object |

***

### 🚀 2. Ramp / Sweep Rate

| Function       | Lake Shore 625 | IPS120   | Mercury IPS          | Notes                   |
| -------------- | -------------- | -------- | -------------------- | ----------------------- |
| Set ramp rate  | `RATE <val>`   | `S<val>` | `SET:...:RSET <val>` | Same role               |
| Read ramp rate | `RATE?`        | `R4`     | `READ:...:RSET?`     | IPS120 register         |
| Rate units     | A/s            | A/s      | A/s or T/s           | Mercury depends on mode |

***

### ⚙️ 3. Ramp Execution / State

| Function               | Lake Shore 625 | IPS120 | Mercury IPS   | Notes                     |
| ---------------------- | -------------- | ------ | ------------- | ------------------------- |
| Start ramp to setpoint | `RAMP`         | `A1`   | `ACTN RTOS`   | Equivalent behaviour      |
| Hold / stop ramp       | `STOP`         | `A0`   | `ACTN HOLD`   | Same purpose              |
| Ramp to zero           | `ZERO`         | `A2`   | `ACTN RTOZ`   | Same                      |
| Clamp / emergency      | —              | `A3`   | (fault state) | IPS120 has explicit clamp |

***

### 🔌 4. Output Enable / Control Mode

| Function       | Lake Shore 625 | IPS120  | Mercury IPS        | Notes                           |
| -------------- | -------------- | ------- | ------------------ | ------------------------------- |
| Enable output  | `OUTMODE 1`    | `C1`    | `SET:...:ENAB ON`  | IPS120 mixes enable + remote    |
| Disable output | `OUTMODE 0`    | `C0`    | `SET:...:ENAB OFF` |                                 |
| Remote mode    | implicit       | `C1/C2` | implicit           | IPS120 unique control structure |
| Local mode     | front panel    | `C0`    | system-level       |                                 |

***

### 🔥 5. Persistent Switch (Heater)

| Function                | Lake Shore 625 | IPS120 | Mercury IPS        | Notes                |
| ----------------------- | -------------- | ------ | ------------------ | -------------------- |
| Heater ON               | `PSH 1`        | `H1`   | `SET:...:SWHT ON`  | Drives magnet        |
| Heater OFF              | `PSH 0`        | `H0`   | `SET:...:SWHT OFF` | Persistent mode      |
| Read persistent current | `PSCUR?`       | `R3`   | `READ:...:PCUR?`   | IPS120 uses register |

***

### 📊 6. Voltage & Measurement

| Function     | Lake Shore 625 | IPS120 | Mercury IPS      | Notes          |
| ------------ | -------------- | ------ | ---------------- | -------------- |
| Read voltage | `RDGV?`        | `R2`   | `READ:...:VOLT?` | Direct mapping |
| Read current | `RDGI?`        | `R1`   | `READ:...:CURR?` |                |
| Read demand  | `SETI?`        | `R0`   | `READ:...:CURR?` |                |

***

### ⚡ 7. Limits & Protection

| Function           | Lake Shore 625       | IPS120          | Mercury IPS         | Notes                    |
| ------------------ | -------------------- | --------------- | ------------------- | ------------------------ |
| Read current limit | `LIMIT?` (or config) | `R5`            | `READ:...:CLIM?`    | IPS120 explicit register |
| Read voltage limit | config               | `R6`            | `READ:...:VLIM?`    |                          |
| Set limits         | model-dependent      | typically fixed | `SET:...:CLIM/VLIM` | Mercury most flexible    |

***

### 📡 8. Status / Diagnostics

| Function        | Lake Shore 625    | IPS120         | Mercury IPS       | Notes                      |
| --------------- | ----------------- | -------------- | ----------------- | -------------------------- |
| Read status     | `RDGST?`          | `X`            | `READ:...:STAT?`  | All different formats      |
| Status format   | numeric/bit-coded | encoded string | structured string | Parsing complexity differs |
| Fault reporting | via status bits   | via `X` string | explicit flags    | Mercury richest            |

***

### ⚙️ 9. Polarity / Direction

| Function         | Lake Shore 625    | IPS120  | Mercury IPS                | Notes           |
| ---------------- | ----------------- | ------- | -------------------------- | --------------- |
| Polarity control | internal/implicit | `D0/D1` | implicit/system controlled | IPS120 explicit |
| Reverse current  | automatic         | via `D` | automatic                  |                 |

***

### 🧠 10. Control Model Commands (Grouped)

#### ✅ Lake Shore 625 (flat procedural)

```text
SETI
RATE
RAMP
STOP
ZERO
OUTMODE
PSH
RDGI?
RDGV?
RDGST?
```

***

#### ✅ IPS120 (compact state-machine)

```text
I     → target
S     → ramp rate
A     → activity (A0–A3)
H     → heater
C     → control mode
D     → polarity
R0–R6 → registers
X     → status
```

***

#### ✅ Mercury IPS (hierarchical system)

```text
SET:DEV:...:CURR
SET:DEV:...:RSET
SET:DEV:...:ACTN
SET:DEV:...:ENAB
SET:DEV:...:SWHT
READ:DEV:...:CURR?
READ:DEV:...:VOLT?
READ:DEV:...:STAT?
```

***

## 🔍 11. Commands With NO Direct Equivalent

### ✅ Unique to IPS120

| Command | Purpose                      |
| ------- | ---------------------------- |
| `A3`    | Clamp / fast safe state      |
| `D0/D1` | Explicit polarity control    |
| `X`     | Compact full-status encoding |

***

### ✅ Unique to Mercury IPS

| Command                   | Purpose                |
| ------------------------- | ---------------------- |
| `DEV:GRPX/Y/Z`            | Multi-axis magnets     |
| `SIG:FIELD`               | Field-native control   |
| Structured `STAT`         | Rich diagnostics       |
| `ENAB` separate from mode | Explicit output enable |

***

### ✅ Unique to Lake Shore 625

| Command                  | Purpose                          |
| ------------------------ | -------------------------------- |
| `RAMP` / `STOP` / `ZERO` | Direct execution (no state code) |
| Flat readable commands   | Easier scripting                 |
| No encoded status string | Simpler parsing                  |

***

## 🧠 12. True One-to-One Equivalence Summary

### Core shared control set

| Physical concept | LS625  | IPS120 | Mercury     |
| ---------------- | ------ | ------ | ----------- |
| Target           | `SETI` | `I`    | `CURR`      |
| Ramp rate        | `RATE` | `S`    | `RSET`      |
| Start            | `RAMP` | `A1`   | `ACTN RTOS` |
| Stop             | `STOP` | `A0`   | `ACTN HOLD` |
| Zero             | `ZERO` | `A2`   | `ACTN RTOZ` |
| Heater           | `PSH`  | `H`    | `SWHT`      |

***

## ✅ Final Interpretation

### 🔑 All three share the same physical control loop

```text
Target → Ramp rate → State → Output → Magnet
```

***

### ⚖️ But differ in *how commands express this*

| Instrument  | Expression                        |
| ----------- | --------------------------------- |
| **LS625**   | Direct actions (“do ramp”)        |
| **IPS120**  | Encoded state (`A1`, `A0`)        |
| **Mercury** | Named state machine (`ACTN RTOS`) |

***

### 🧠 One-line comparison

* **LS625** → procedural command interface
* **IPS120** → compact symbolic state machine
* **Mercury IPS** → structured, system-level API

***
