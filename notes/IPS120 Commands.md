# 📘 IPS120 Programmer’s Reference (Chapter 8–aligned)

***

***

## 🧭 1. Command Model Overview

The IPS120 uses a **single-layer command system**:

* **Immediate commands only**
* No programmable tables (unlike ITC503 Chapter 10)
* State-machine driven (activity, heater, limits)

***

### ✅ Command types

| Type          | Format            | Example |
| ------------- | ----------------- | ------- |
| Set / control | `<Letter><value>` | `I50.0` |
| Read register | `R<n>`            | `R1`    |
| Status        | `X`               | `X`     |

***

## 📊 2. Readback Registers (`R`)

### 🔹 Core registers

```text
R0   → Demand current (setpoint)
R1   → Measured current
R2   → Measured voltage
R3   → Persistent current
R4   → Ramp rate
R5   → Current limit
R6   → Voltage limit
R7   → Measured field (when fitted / field mode active)
```

***

### 🔹 Control mode notes

* Units depend on instrument configuration:
  * Current mode (A)
  * Field mode (T)
* Values are returned as numeric ASCII

***

## ⚙️ 3. Core Control Commands

### 🔹 `I` — Set current / field target

```text
I<value>
```

Example:

```text
I50.0
```

* Sets demand current (or field if calibrated)
* Does **not start ramping**

***

### 🔹 `S` — Set sweep (ramp) rate

```text
S<value>
```

Example:

```text
S0.2
```

* Defines ramp rate (A/s or T/s)
* Applies to subsequent ramps

***

### 🔹 `A` — Activity (state machine)

```text
A0 → Hold  
A1 → Ramp to demand  
A2 → Ramp to zero  
A3 → Clamp (fast stop / safe state)
```

***

### 🔹 Behaviour summary

| Command | Action                                     |
| ------- | ------------------------------------------ |
| `A0`    | Stop ramp, hold current                    |
| `A1`    | Ramp to `I` setpoint                       |
| `A2`    | Ramp to zero                               |
| `A3`    | Emergency clamp (implementation dependent) |

***

## 🔥 4. Persistent Switch Control

### 🔹 `H` — Heater control

```text
H0 → Heater OFF (persistent mode ON)
H1 → Heater ON (power supply drives current)
```

***

### 🔹 Protection behaviour

| Heater | Mode                   |
| ------ | ---------------------- |
| ON     | Driven mode            |
| OFF    | Persistent magnet mode |

***

### 🔹 Important constraint

* You should **only ramp with heater ON**
* Switching heater OFF traps current in magnet

***

## 🧲 5. Polarity / Output Direction

### 🔹 `D` — Polarity (if fitted)

```text
D0 → Positive  
D1 → Negative
```

⚠️ Not all systems expose polarity control (depends on wiring/config)

***

## ⚙️ 6. Control / Mode Settings

### 🔹 `C` — Control mode

```text
C0 → Local control
C1 → Remote & locked
C2 → Remote & unlocked
```

***

### 🔹 Notes

* Required for remote automation
* Typical usage:

```text
C1
```

***

## 📡 7. Status Command

### 🔹 `X` — System status string

```text
X
```

Returns encoded string, e.g.:

```text
X0A1H1M00P00
```

***

### 🔹 Key fields

| Field | Meaning                   |
| ----- | ------------------------- |
| `A`   | Activity (ramp/hold/zero) |
| `H`   | Heater state              |
| `M`   | Magnet mode               |
| `P`   | Protection state          |

***

### 🔹 Interpretation

Must parse character-by-character — no delimiters.

***

## 🔌 8. Limit and Protection System

### 🔹 Read-only via registers

```text
R5 → Current limit  
R6 → Voltage limit  
```

***

### 🔹 Behaviour

* Limits are enforced automatically
* If exceeded:
  * Ramp slows or halts
  * System may enter clamp state

***

## ⚠️ 9. Protection / Fault Behaviour

### 🔹 `A3` — Clamp (if supported)

* Immediately stops ramp
* Forces safe output behaviour

***

### 🔹 Fault indications

* Reflected in `X` status string
* May include:
  * Quench
  * Overvoltage
  * External trip

***

## 🧠 10. Internal Control Model

```text
          ┌────────────────────┐
          │ Demand Current (I) │
          └─────────┬──────────┘
                    │
          ┌─────────▼──────────┐
          │ Ramp Rate (S)      │
          └─────────┬──────────┘
                    │
          ┌─────────▼──────────┐
          │ Activity (A)       │
          └─────────┬──────────┘
                    │
          ┌─────────▼──────────┐
          │ Output stage       │
          └─────────┬──────────┘
                    │
          ┌─────────▼──────────┐
          │ Magnet + Heater H  │
          └────────────────────┘
```

***

## 🧪 11. Complete Command List (Chapter 8 Summary)

### ✅ Control commands

```text
A0–A3    → Activity control  
C0–C2    → Control/remote mode  
D0–D1    → Output polarity (if available)  
H0–H1    → Persistent switch heater  
I<value> → Set current/field  
S<value> → Set ramp rate  
```

***

### ✅ Readback commands

```text
R0–R7 → System registers  
X     → Full status string  
```

***

## 🧪 12. Minimal Working Sequences

### 🔹 Ramp to field

```text
C1        → remote control  
H1        → heater ON  
I50.0     → target current  
S0.2      → ramp rate  
A1        → start ramp  
```

***

### 🔹 Hold current

```text
A0
```

***

### 🔹 Go to zero

```text
A2
```

***

### 🔹 Enter persistent mode

```text
A0  
H0  
```

***

### 🔹 Read state

```text
R1   → current  
R2   → voltage  
R4   → ramp rate  
R7   → field  
X    → full system state  
```

***

## ⚖️ 13. Key Differences vs ITC503

| Feature             | ITC503 | IPS120 |
| ------------------- | ------ | ------ |
| Registers           | Yes    | Yes    |
| PID control         | Yes    | No     |
| PID tables          | Yes    | No     |
| Sweep program       | Yes    | No     |
| Continuous ramp     | No     | Yes    |
| Internal automation | High   | Low    |

***

## ✅ Final Takeaways

The IPS120 is:

### ✅ A **deterministic ramp controller**

* Everything defined by:
  * Target (`I`)
  * Rate (`S`)
  * State (`A`)

***

#### ✅ A **state machine**

* Controlled via:
  * `A` activity
  * `H` heater
  * `C` control mode

***

#### ⚠️ Key operational constraints

* Heater must be **ON for ramping**
* Persistent mode must be handled carefully
* Status parsing (`X`) is essential for safe control

***
