# Lake Shore temperature controller command comparison

Below is a **three‑way, command‑by‑command diffable summary** of the Lake Shore
**340 (Ch.9)**, **335 (Ch.6)**, and **336 (Ch.6.6)** command sets.

I’ve kept the same classification scheme and added **336 as a third column** so
you can directly see how the command model evolves:

- ✅ **IDENTICAL** — same syntax + semantics across all models
- ⚠️ **SEMANTIC CHANGE** — same command name, meaning differs
- ➕ **ADDED** — appears in later model(s) only
- ❌ **REMOVED** — absent in later model(s)

---

## 🔷 1. IEEE‑488.2 COMMANDS (all three)

```text
*CLS
*ESE       / *ESE?
*ESR?
*IDN?
*OPC       / *OPC?
*RST
*SRE       / *SRE?
*STB?
*TST?
```

| 340 | 335 | 336 |
| --- | --- | --- |
| ✅  | ✅  | ✅  |

✅ **Fully identical across all three**

---

## 🔷 2. TEMPERATURE READBACK

```text
KRDG? <input>
CRDG? <input>
SRDG? <input>
RDGST? <input>
```

| Command | 340 | 335 | 336 |
| ------- | --- | --- | --- |
| KRDG?   | ✅  | ✅  | ✅  |
| CRDG?   | ✅  | ✅  | ✅  |
| SRDG?   | ✅  | ✅  | ✅  |
| RDGST?  | ✅  | ✅  | ✅  |

### Readback differences

| Aspect | 340                   | 335  | 336        |
| ------ | --------------------- | ---- | ---------- |
| Inputs | A, B + optional cards | A, B | A, B, C, D |

⚠️ **Key semantic drift**

- 336 expands input namespace:

  ```text
  A, B → A, B, C, D
  ```

✅ Syntax unchanged

⚠️ Input addressing expanded

---

## 🔷 3. SETPOINT / RAMP

```text
SETP <loop>,<value>
SETP? <loop>

RAMP <loop>,<on/off>,<rate>
RAMP? <loop>
```

| Command | 340 | 335 | 336 |
| ------- | --- | --- | --- |
| SETP    | ⚠️  | ⚠️  | ⚠️  |
| RAMP    | ⚠️  | ⚠️  | ⚠️  |

### Diff evolution

| Model | Interpretation of loop placeholder |
| ----- | ---------------------------------- |
| 340   | implicit control loop              |
| 335   | output 1 or 2                      |
| 336   | output 1–4                         |

⚠️ **Progression**

```text
340: logical loop
335: physical output (2)
336: physical outputs (up to 4)
```

---

## 🔷 4. PID CONTROL

```text
PID <loop>,<P>,<I>,<D>
PID? <loop>
```

| 340 | 335 | 336 |
| --- | --- | --- |
| ⚠️  | ⚠️  | ⚠️  |

### Semantic evolution

| Model | Meaning                           |
| ----- | --------------------------------- |
| 340   | PID tied to control configuration |
| 335   | PID tied to output 1 / 2          |
| 336   | PID tied to output 1–4            |

✅ Syntax identical

⚠️ Increasing decoupling from “control loop” to **independent outputs**

---

## 🔷 5. OUTPUT RANGE

```text
RANGE <loop>,<range>
RANGE? <loop>
```

| 340 | 335 | 336 |
| --- | --- | --- |
| ⚠️  | ⚠️  | ⚠️  |

### Diff pattern

| Model | Output mapping   |
| ----- | ---------------- |
| 340   | main heater path |
| 335   | output 1 / 2     |
| 336   | output 1–4       |

⚠️ Also:

- 336 introduces wider heater configuration flexibility

---

## 🔷 6. MANUAL OUTPUT

```text
MOUT <loop>,<percent>
MOUT? <loop>
```

| 340 | 335 | 336 |
| --- | --- | --- |
| ⚠️  | ⚠️  | ⚠️  |

### Manual output evolution

| Model | Meaning                      |
| ----- | ---------------------------- |
| 340   | manual control of loop       |
| 335   | manual control of output 1/2 |
| 336   | manual control of output 1–4 |

---

## 🔷 7. CONTROL MODE

```text
CMODE <loop>,<mode>
CMODE? <loop>
```

| 340 | 335 | 336 |
| --- | --- | --- |
| ⚠️  | ⚠️  | ⚠️  |

### Mode expansion

| Model | Notes                                      |
| ----- | ------------------------------------------ |
| 340   | PID / manual / limited options             |
| 335   | adds zone control                          |
| 336   | more complete zone + autotune combinations |

⚠️ Same command name  
⚠️ Mode values expand significantly

---

## 🔷 8. INPUT CONFIGURATION

```text
INTYPE <input>,<params>
INTYPE? <input>

FILTER <input>,<params>
FILTER? <input>
```

| Command | 340 | 335 | 336 |
| ------- | --- | --- | --- |
| INTYPE  | ⚠️  | ⚠️  | ⚠️  |
| FILTER  | ⚠️  | ⚠️  | ⚠️  |

### Diff

| Feature              | 340        | 335     | 336            |
| -------------------- | ---------- | ------- | -------------- |
| Capacitance sensors  | ✅         | ❌      | ❌             |
| # inputs             | up to many | 2       | 4              |
| parameter complexity | highest    | reduced | expanded again |

⚠️ 336 re-expands:

- more channels
- more configuration permutations

---

## 🔷 9. CURVE COMMANDS

```text
CRVHDR <n>,...
CRVHDR? <n>

CRVPT <n>,...
CRVPT? <n>

CRVDEL <n>
CRVDEL? <n>
```

| 340 | 335 | 336 |
| --- | --- | --- |
| ⚠️  | ⚠️  | ⚠️  |

### Curve command differences

| Model | Notes                                     |
| ----- | ----------------------------------------- |
| 340   | supports legacy + capacitance curves      |
| 335   | simplified                                |
| 336   | similar to 335 but scaled for more inputs |

⚠️ Main divergence:

- allowed formats and indexing

---

## 🔷 10. ALARMS

```text
ALARM <input>,<params>
ALARM? <input>
ALMRST
```

| 340 | 335 | 336 |
| --- | --- | --- |
| ⚠️  | ⚠️  | ⚠️  |

### Alarm evolution

| Model | Features                                 |
| ----- | ---------------------------------------- |
| 340   | basic limits                             |
| 335   | expanded fields                          |
| 336   | more structured, tied to multiple inputs |

---

## 🔷 11. STATUS / SYSTEM

```text
STAT?
```

| 340 | 335 | 336 |
| --- | --- | --- |
| ✅  | ✅  | ✅  |

⚠️ Bit definitions evolve (especially in 336)

---

## 🔷 12. 340‑ONLY COMMANDS

```text
CAP*
CSET*
SCAN*
(expansion-card specific commands)
```

| 340 | 335 | 336 |
| --- | --- | --- |
| ✅  | ❌  | ❌  |

✅ Completely removed from later models

---

## 🔷 13. 335‑ONLY ADDITIONS

Primarily:

```text
ZONE
ZONE?
```

| 340 | 335 | 336 |
| --- | --- | --- |
| ❌  | ➕  | ✅  |

✅ 336 inherits and expands zone features

---

## 🔷 14. 336‑ONLY ADDITIONS / EXTENSIONS

### Capability expansions rather than new command names

- Expanded addressing:

  ```text
  input:  A,B → A,B,C,D
  output: 1 → 1,2 → 1,2,3,4
  ```

- Extended commands (same names):

  ```text
  SETP, PID, RANGE, CMODE, MOUT
  ```

➕ **True “additions” are mostly capability expansions, not new keywords**

---

## 🔷 15. GLOBAL DIFF SUMMARY

### ✅ Identical across all three (\~60%)

- IEEE‑488.2 commands
- Basic readback (KRDG, etc.)
- Structural syntax of most commands

---

### ⚠️ Same command, evolving meaning (\~30%)

Core group:

```text
SETP
RAMP
PID
RANGE
MOUT
CMODE
INTYPE
FILTER
CRVHDR
CRVPT
ALARM
```

### Zone-control evolution pattern

```text
340 → loop-centric, implicit hardware
335 → output-centric (2 channels)
336 → scalable (4 outputs, 4 inputs)
```

---

### ❌ Removed after 340 (\~5%)

- Capacitance input commands
- Scanner / expansion card commands

---

### ➕ Added in 335 / extended in 336 (\~5%)

- Zone control
- Output addressing extensions
- Expanded parameter ranges

---

## ✅ Final (driver-level view)

### Command evolution

```text
340: legacy + hardware-specific (capacitance, expansion)
335: cleaned, 2-channel abstraction
336: generalized N-channel controller (4×4 matrix)
```

---

### ✅ Core migration rules (all three)

### 1. Loop abstraction changes

```text
340 → implicit loop
335 → output (1–2)
336 → output (1–4)
```

### 2. Input addressing expands

```text
340 → cards
335 → A,B only
336 → A,B,C,D (native)
```

### 3. Feature removal

- Must remove:
  - CAP\*, SCAN\*, expansion commands

### 4. Parameter reinterpretation

- Same syntax ≠ same behavior:
  - PID
  - RANGE
  - CMODE

---
