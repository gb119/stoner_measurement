***

# 📘 ITC503 Programmer’s Reference Sheet

***

# 🧭 1. Command Model Overview

The ITC503 has **two layers of control**:

## 🔹 Layer 1 – Real‑time control (Chapter 9)

* Immediate commands (single letter)
* Register readback (`Rn`)
* Used for:
  * Setpoint
  * PID (current values)
  * Heater control
  * Status

***

## 🔹 Layer 2 – Programmed control (Chapter 10)

* “Specialist” commands
* Used to configure:
  * ✅ PID tables
  * ✅ Sweep (temperature program) tables

***

# 🔌 2. Command Syntax

## ✅ Write commands

```
<Letter><value>
```

Examples:

```
T300     → set temperature
P20      → proportional band
O50      → 50% heater
```

***

## ✅ Read commands

```
Rn
```

Returns integer (scaled; see instrument settings)

***

## ✅ Status query

```
X
```

Returns encoded status string

***

# 📊 3. Read Registers (Chapter 9)

## 🔹 Core registers

```
R0   → Set temperature  
R1   → Sensor 1 temperature  
R2   → Sensor 2 temperature  
R3   → Sensor 3 temperature  
R4   → Temperature error (Set − Measured)  
R5   → Heater output (% of current limit)  
R6   → Heater output (Volts, approx.)  
R7   → Gas flow output  
R8   → Proportional band  
R9   → Integral time  
R10  → Derivative time  
```

***

## 🔹 Diagnostics

```
R11 → Channel 1 frequency / 4  
R12 → Channel 2 frequency / 4  
R13 → Channel 3 frequency / 4  
```

***

# 🌡️ 4. Temperature & Control Commands

## 🔹 Setpoint

```
Tvalue     → Set temperature
R0         → Read setpoint
```

***

## 🔹 Control mode

```
A0  → Manual  
A1  → Automatic (PID)  
A2  → Auto (variant-dependent mode)
```

***

## 🔹 Sensor selection

```
C0 → Sensor 1  
C1 → Sensor 2  
C2 → Sensor 3  
```

***

# 🔥 5. Heater Control

```
Ovalue   → Set manual heater output (%)  
Hn       → Heater range (0–max)  
```

Read:

```
R5 → Heater %  
R6 → Heater voltage  
```

***

# ⚙️ 6. PID Control (Immediate)

## 🔹 Set

```
Pvalue   → Proportional band  
Ivalue   → Integral time  
Dvalue   → Derivative time  
```

## 🔹 Read

```
R8 → P  
R9 → I  
R10 → D  
```

***

# 🚀 7. Sweep Control (Execution – Chapter 9)

```
S0  → Stop sweep  
S1  → Start sweep  
Sn  → Jump to program step n (2–32)
```

### 🔹 Behaviour rules

* `S1` → continue from current step
* `Sn (n ≥ 2)`:
  * Jump to step
  * If **odd (≠1)**:
    * Jump to previous step temperature
    * Then sweep forward

***

# 📡 8. Status String (`X`)

Example:

```
X0A1C1S05H2L0
```

### 🔹 Key fields

| Code | Meaning          |
| ---- | ---------------- |
| `A`  | Control mode     |
| `C`  | Sensor selection |
| `S`  | Sweep step       |
| `H`  | Heater range     |
| `L`  | Control limits   |

👉 Must be parsed character-by-character

***

# 🗂️ 9. Chapter 10 – Specialist Commands

This is where the ITC503 becomes **programmable and stateful**.

***

# ⚙️ 9.1 PID Table Programming

## ✅ Concept

You define **multiple PID sets** tied to temperature regions:

```
Temperature range → P, I, D
```

***

## ✅ Capabilities

* Store multiple PID entries
* Automatically select based on temperature
* Smooth control over wide temperature ranges

***

## ✅ Structure (conceptual)

```
Entry n:
  T_low
  T_high
  P
  I
  D
```

***

## ✅ Use case

Instead of:

* Constant PID → unstable across large range

You get:

* Low-T PID
* Mid-T PID
* High-T PID

Switched automatically

***

# 🚀 9.2 Sweep Table Programming

## ✅ Concept

Defines a **multi-step temperature program**

***

## ✅ Each step includes:

* Target temperature
* Sweep characteristics
* Control behaviour

***

## ✅ Structure (conceptual)

```
Step 1: T1  
Step 2: T2  
Step 3: T3  
...
Step N
```

***

## ✅ Execution

```
S1 → start  
S5 → jump to step 5  
S0 → stop  
```

***

## ✅ Special behaviour

* Odd step entry triggers **pre-step temperature snap**
* Even steps → normal progression

***

# 🧠 10. Internal Model

The ITC503 can be understood as:

```
             ┌─────────────────────┐
             │   PID TABLE         │
             └────────┬────────────┘
                      │
             ┌────────▼────────────┐
             │ Sweep Program (1–32)│
             └────────┬────────────┘
                      │
             ┌────────▼────────────┐
             │ Execution pointer   │ ← S command
             └────────┬────────────┘
                      │
             ┌────────▼────────────┐
             │ Real-time loop      │
             │ (A, P, I, D, O, H) │
             └─────────────────────┘
```

***

# ⚖️ 11. Key Operational Differences vs Modern Controllers

| Feature                  | ITC503 |
| ------------------------ | ------ |
| Immediate control        | ✅      |
| Register-based readback  | ✅      |
| PID table switching      | ✅      |
| Sweep program execution  | ✅      |
| Continuous ramp          | ❌      |
| Self-describing commands | ❌      |

***

# ✅ 12. Minimal Working Command Sequences

## 🔹 Basic temperature control

```
C0        → select sensor 1  
T300      → set temperature  
A1        → enable control  
```

***

## 🔹 Manual heater control

```
A0        → manual  
O40       → 40% output  
```

***

## 🔹 Start programmed temperature run

```
S1        → start sweep program  
```

***

## 🔹 Read everything important

```
R0  → setpoint  
R1  → temperature  
R5  → heater  
R8–10 → PID  
X   → system status  
```

***

# ✅ Final Takeaways

The ITC503 is fundamentally:

### ✅ A hybrid system:

* **Registers (R0–R13)** for live values
* **Immediate commands (T, P, I, D, etc.)**
* **Program tables (Chapter 10)** for automation

***

### ✅ What makes it powerful

* Built-in **temperature programs**
* Automatic **PID region switching**
* Minimal host-side logic required

***

### ⚠️ What makes it tricky

* Non-self-describing commands
* Encoded status (`X`)
* Separate concepts:
  * live control vs programmed control

***

Just say 👍
