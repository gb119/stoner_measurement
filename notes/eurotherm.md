# Eurotherm 32h8 / 3200 Series Modbus RTU Driver Guide

## 1. Physical/link layer

Use Modbus RTU over the optional EIA485/RS485 2-wire port.

Default serial settings:

- Baud: 9600
- Parity: none
- Address: 1
- Valid instrument addresses: 1–254

32h8 RS485 terminals:

- HD = common
- HE = A(+)
- HF = B(-)

Use screened twisted pair plus common where possible. Daisy-chain devices; avoid star wiring. Terminate the final
controller with ~220 Ω if required.

Important: digital communications and remote analogue setpoint are mutually exclusive options.

## 2. Modbus data model

Use 16-bit signed Modbus registers.

Eurotherm decimal/scaled values are transmitted as scaled integers:

- actual value = register_value / 10^decimal_places
- decimal places are determined by the instrument resolution/configuration.
- Example: if resolution is 0.1 °C, 123.4 °C is sent as 1234.

Use function codes:

- Read Holding Registers: normal parameter reads.
- Write Single Register / Write Multiple Registers: parameter writes.
- Broadcast function 6 may be used only for broadcast retransmission use cases.

Driver should expose both:

- raw register read/write
- typed/scaled high-level methods

## 3. EEPROM wear rule

Do not repeatedly write retained parameters. The manual warns of a limited non-volatile memory write life.

For frequent/ramped setpoint updates:

1. Enable remote/comms setpoint selection: write `L-R` at address `276`.
2. Write the running setpoint to `Rm.SP` at address `26`.
3. Refresh `Rm.SP` at least every ~5 s or the controller falls back to local SP and raises remote SP fail.

Avoid high-frequency writes to:

- `TG.SP` address 2
- `SP1` address 24
- `SP2` address 25
- alarm thresholds/hysteresis
- mode/timer/programmer state

## 4. Core process variables

| Function | Mnemonic | Address | R/W | Notes |
| --- | ---: | ---: | --- | --- |
| Process value | `PV.IN` | 1 | R | measured temperature/process value |
| Target setpoint | `TG.SP` | 2 | R/W | do not ramp by repeated writes |
| Manual output value | `MAN.OP` | 3 | R/W | used in manual mode |
| Working output | `WRK.OP` | 4 | R | actual output demand |
| Working setpoint | `WKG.SP` | 5 | R | active effective setpoint |
| Error | `P.Err` | 39 | R | PV - SP |
| Instrument status bitmap | `StAt` | 75 | R | see status bits below |
| Digital input bitmap | `Di.IP` | 87 | R | input states |
| Digital output bitmap | `Di.OP` | 551 | R/W | writable only for telemetry outputs |

## 5. Open/closed loop, standby, manual

Use these for control-mode handling:

| Function | Mnemonic | Address | Values |
| --- | ---: | ---: | --- |
| Instrument mode | `IM` | 199 | `0` operating, `1` standby/control outputs off, `2` config/all outputs inactive |
| Auto/manual loop mode | `A-M` | 273 | `0` auto closed-loop, `1` manual open-loop |
| Manual output value | `MAN.OP` | 3 | output demand in % |
| Forced manual output value | `F.OP` | 84 | forced output |
| Forced manual mode | `F.MOD` | 85 | `0` none, `1` step, `2` last |
| Standby type | `STBY.T` | 530 | `0` absolute alarm outputs active, others off; `1` all outputs inactive |

High-level driver API:

```python
set_auto()        # write A-M = 0
set_manual(pct)   # write MAN.OP, then A-M = 1
set_standby(on)   # write IM = 1 or 0
get_mode()
````

## 6. Setpoint control

| Function                 | Mnemonic | Address | Notes                              |
| ------------------------ | -------: | ------: | ---------------------------------- |
| Select SP1/SP2           | `SP.SEL` |      15 | `0` SP1, `1` SP2                   |
| SP1                      |    `SP1` |      24 | retained; do not ramp              |
| SP2                      |    `SP2` |      25 | retained; do not ramp              |
| Remote/comms setpoint    |  `Rm.SP` |      26 | safe for frequent writes; volatile |
| Local trim               |  `LOC.t` |      27 | added to remote/comms SP           |
| Setpoint high limit      |  `SP.HI` |     111 | retained                           |
| Setpoint low limit       |  `SP.LO` |     112 | retained                           |
| Setpoint rate limit      | `SP.RAT` |      35 | `0` disables rate limit            |
| Local/remote SP select   |    `L-R` |     276 | select remote/comms SP             |
| Remote input high scalar | `REM.HI` |     278 | analogue remote SP option          |
| Remote input low scalar  | `REM.LO` |     279 | analogue remote SP option          |

Recommended ramping method:

```python
enable_remote_setpoint()
while ramping:
    write_scaled(26, setpoint)
    sleep(<5 seconds)
```

## 7. PID and control tuning

| Function                 | Mnemonic | Address | Values/notes                                      |
| ------------------------ | -------: | ------: | ------------------------------------------------- |
| Heat/ch1 control type    | `CTRL.H` |     512 | `0` off, `1` on/off, `2` PID, `3` motorised valve |
| Cool/ch2 control type    | `CTRL.C` |     513 | `0` off, `1` on/off, `2` PID                      |
| Control action           | `CTRL.A` |       7 | `0` reverse acting, `1` direct acting             |
| Proportional band        |     `PB` |       6 | scaled                                            |
| Integral time            |     `Ti` |       8 | `0` disables integral                             |
| Derivative time          |     `Td` |       9 | `0` disables derivative                           |
| Relative cool gain       |    `R2G` |      19 | cooling PB relative to heating PB                 |
| Deadband                 | `D.BAND` |      16 | ch2 deadband                                      |
| Cutback low              |  `CB.Lo` |      17 | overshoot/start-up tuning                         |
| Cutback high             |  `CB.HI` |      18 | overshoot/start-up tuning                         |
| Manual reset             |     `MR` |      28 | used with P/PD/on-off contexts                    |
| Output high limit        |  `OP.HI` |      30 | max output                                        |
| Output low limit         |  `OP.LO` |      31 | min output                                        |
| Safe output              |   `SAFE` |      34 | output under sensor break/fault                   |
| Loop break time          |    `LBT` |      83 | loop-break detection                              |
| Heat hysteresis          | `HYST.H` |      86 | on/off control                                    |
| Cool hysteresis          | `HYST.C` |      88 | on/off control                                    |
| Cooling algorithm        | `COOL.t` |     524 | `0` linear, `1` oil, `2` water, `3` fan           |
| Auto-tune enable         | `A.TUNE` |     270 | `0` off, `1` enabled                              |
| Auto-tune configures R2G | `AT.R2G` |    4176 | `0` yes, `1` no                                   |

High-level methods:

```python
configure_pid(pb, ti, td, r2g=None, cb_low=None, cb_high=None)
set_control_type(heat="pid", cool="off|onoff|pid")
start_autotune()
stop_autotune()
```

## 8. Input configuration

| Function          | Mnemonic | Address | Values                                                                                                 |
| ----------------- | -------: | ------: | ------------------------------------------------------------------------------------------------------ |
| Input sensor type | `IN.TYP` |   12290 | `0` J, `1` K, `2` L, `3` R, `4` B, `5` N, `6` T, `7` S, `8` RTD, `9` mV, `10` comms input, `11` custom |
| CJC type          | `CJ.tyP` |   12291 | `0` auto, `1` 0 °C, `2` 50 °C                                                                          |
| Input range low   | `RNG.LO` |      11 | scaled                                                                                                 |
| Input range high  | `RNG.HI` |      12 | scaled                                                                                                 |
| PV offset         | `PV.OFS` |     141 | scaled                                                                                                 |
| Input filter time | `FILT.T` |     101 | scaled                                                                                                 |
| mV low            |  `mV.LO` |   12307 | linear input scaling                                                                                   |
| mV high           |  `mV.HI` |   12306 | linear input scaling                                                                                   |
| Comms PV value    |  `PV.CM` |     203 | external PV when input type = comms                                                                    |

If `IN.TYP = 10`, write the process variable to `PV.CM` at least every ~5 s if sensor-break detection is enabled.

## 9. Alarms

| Function               | Address |
| ---------------------- | ------: |
| Alarm 1 threshold      |      13 |
| Alarm 2 threshold      |      14 |
| Alarm 3 threshold      |      81 |
| Alarm 4 threshold      |      82 |
| Alarm 1 hysteresis     |      47 |
| Alarm 2 hysteresis     |      68 |
| Alarm 3 hysteresis     |      69 |
| Alarm 4 hysteresis     |      71 |
| Alarm 1 status         |     294 |
| Alarm 2 status         |     295 |
| Alarm 3 status         |     296 |
| Alarm 4 status         |     297 |
| Acknowledge all alarms |     274 |
| New alarm status       |     260 |
| Sensor break status    |     258 |
| Loop break status      |     263 |

Alarm configuration:

- `A1.TYP` etc. define alarm type.
- `A1.LAT`–`A4.LAT` at 540–543 define latching: `0` none, `1` automatic reset, `2` manual reset.
- `A1.BLK`–`A4.BLK` at 544–547 enable blocking: `0` off, `1` block.

## 10. Status bitmap: address 75

`StAt` bits:

- B0 alarm 1
- B1 alarm 2
- B2 alarm 3
- B3 alarm 4
- B4 manual mode active
- B5 sensor break
- B6 loop break
- B7 CT low load current alarm
- B8 CT high leakage current alarm
- B9 program end
- B10 PV over-range by >5% span
- B11 CT overcurrent
- B12 new alarm
- B13 timer/ramp running
- B14 remote/comms SP fail
- B15 auto-tune active

Address 76 is the inverted status word.

## 11. Timer/programmer

| Function                |       Mnemonic | Address | Values                                                                                |
| ----------------------- | -------------: | ------: | ------------------------------------------------------------------------------------- |
| Timer status            |       `T.STAT` |      23 | `0` reset, `1` run, `2` hold, `3` end                                                 |
| Timer type              |       `TM.CFG` |     320 | `0` none, `1` dwell, `2` delay, `3` soft start, `10` programmer                       |
| Timer resolution        |       `TM.RES` |     321 | `0` hours:min, `1` min:sec                                                            |
| Soft-start SP           |        `SS.SP` |     322 | scaled                                                                                |
| Soft-start power limit  |       `SS.PWR` |     323 | %                                                                                     |
| Requested dwell         |        `DWELL` |     324 | scaled time                                                                           |
| Elapsed time            |       `T.ELAP` |     325 | read                                                                                  |
| Remaining time          |       `T.REMN` |     326 | read                                                                                  |
| Timer threshold         |        `THRES` |     327 | scaled                                                                                |
| End type                |        `End.T` |     328 | `0` off, `1` dwell at current SP, `2` transfer to SP2 and dwell, `3` reset programmer |
| Servo mode              |        `SERVO` |     329 | programmer start/restart behaviour                                                    |
| Event outputs           |        `EVENT` |     331 | event bitfield/value                                                                  |
| Program cycles          |       `P.CYCL` |     332 | number of cycles                                                                      |
| Current cycle           |        `CYCLE` |     333 | read                                                                                  |
| Segment 1 dwell/SP/ramp | 1280/1281/1282 |         |                                                                                       |
| Segment 2 dwell/SP/ramp | 1283/1284/1285 |         |                                                                                       |
| Segment 3 dwell/SP/ramp | 1286/1287/1288 |         |                                                                                       |
| Segment 4 dwell/SP/ramp | 1289/1290/1291 |         |                                                                                       |

## 12. Output channel configuration

For a 32h8, outputs can include I/O1, OP2, OP3, and AA relay OP4 depending on order code.

Function values:

- `0` none/telemetry
- `1` digital output
- `2` heat/up
- `3` cool/down
- `10` DC output no function
- `11` DC heat
- `12` DC cool
- `13` DC WSP retransmission
- `14` DC PV retransmission
- `15` DC OP retransmission

Key addresses:

- I/O1: type `12672`, function `12675`, DC range `12676`, sources `12678–12681`, polarity `12682`, min pulse `12706`
- OP2: type `12736`, function `12739`, DC range `12740`, sources `12742–12745`, polarity `12746`, min pulse `12770`
- OP3: type `12800`, function `12803`, DC range `12804`, sources `12806–12809`, polarity `12810`, min pulse `12834`
- OP4/AA: type `13056`, function `13059`, sources `13062–13065`, polarity `13066`, min pulse `13090`

Output source values:

- `0` none
- `1` alarm 1
- `2` alarm 2
- `3` alarm 3
- `4` alarm 4
- `5` all alarms
- `6` new alarm
- `7` CT alarm
- `8` loop break
- `9` sensor break
- `10` timer end / not ramping
- `11` timer run / ramping
- `12` auto/manual
- `13` remote fail
- `14` power fail
- `15` programmer event

## 13. Digital inputs

Input function values:

- `40` none
- `41` acknowledge all alarms
- `42` select SP1/SP2
- `43` lock all keys
- `44` timer reset
- `45` timer run
- `46` timer run/reset
- `47` timer hold
- `48` auto/manual select
- `49` standby select
- `50` remote setpoint
- `51` recipe select through IO1
- `52` remote key up
- `53` remote key down

Addresses:

- Logic input A type: `12352`
- Logic input A function: `12353`
- Logic input A polarity: `12361`
- Logic input B type: `12368`
- Logic input B function: `12369`
- Logic input B polarity: `12377`
- I/O1 digital input function: `12673`

## 14. Current transformer / heater diagnostics

| Function                              | Address |
| ------------------------------------- | ------: |
| Load leakage current                  |      79 |
| Load ON current                       |      80 |
| Low load current threshold            |     304 |
| High leakage current threshold/status |     305 |
| Overcurrent threshold                 |     306 |
| Load alarm status                     |     307 |
| Leak alarm status                     |     308 |
| Overcurrent alarm status              |     309 |
| CT range                              |     572 |
| CT module ID                          |   12608 |
| CT source                             |   12609 |
| CT alarm latch type                   |   12610 |

CT source:

- `0` none
- `1` IO1
- `2` OP2
- `8` AA/OP4

## 15. Recipes

| Function      | Address |
| ------------- | ------: |
| Recall recipe |     313 |
| Save recipe   |     314 |

Recipes store common control parameters including PID terms, cutbacks, SP1/SP2, output limits, alarm
thresholds/hysteresis, timer parameters, units/resolution, and related configuration.

## 16. Minimal driver class interface

Recommended public API:

```python
class Eurotherm32h8:
    def read_raw(address: int) -> int: ...
    def write_raw(address: int, value: int) -> None: ...

    def read_scaled(address: int, dp: int) -> float: ...
    def write_scaled(address: int, value: float, dp: int) -> None: ...

    def get_pv() -> float: ...
    def get_working_setpoint() -> float: ...
    def get_working_output() -> float: ...
    def get_status() -> dict: ...

    def set_sp1(value: float) -> None: ...
    def set_sp2(value: float) -> None: ...
    def select_sp(index: int) -> None: ...

    def enable_remote_setpoint() -> None: ...
    def write_remote_setpoint(value: float) -> None: ...

    def set_auto() -> None: ...
    def set_manual(output_percent: float) -> None: ...
    def set_standby(enabled: bool) -> None: ...

    def configure_pid(pb, ti, td, r2g=None, cb_low=None, cb_high=None) -> None: ...
    def set_control_type(heat: str, cool: str) -> None: ...
    def start_autotune() -> None: ...
    def stop_autotune() -> None: ...

    def acknowledge_alarms() -> None: ...
    def get_alarms() -> dict: ...

    def timer_run() -> None: ...
    def timer_hold() -> None: ...
    def timer_reset() -> None: ...
```

## 17. Safe operating sequence

1. Connect RS485 and verify serial settings.
2. Read instrument type/version/address.
3. Read PV, WKG.SP, WRK.OP, StAt.
4. Decode status and refuse control if sensor break, loop break, over-range, or remote SP fail is active unless
   explicitly overridden.
5. For closed-loop temperature control, set `A-M = 0`.
6. For open-loop/manual control, set `MAN.OP`, then `A-M = 1`.
7. For frequent setpoint updates, use `L-R` + `Rm.SP`, not `SP1`, `SP2`, or `TG.SP`.

## Eurotherm 2000 Series Modbus / EI-Bisynch Driver Guide

Applies mainly to Eurotherm 2200 and 2400 series instruments.

## 1. Main similarity to 3200 series

The 2000 and 3200 series share many core Modbus addresses:

| Function | 2000 address | 3200 address | Notes |
| --- | ---: | ---: | --- |
| Process value | 1 | 1 | same |
| Target setpoint | 2 | 2 | same, but avoid repeated writes |
| Output power / manual output | 3 | 3 | same |
| Working output | 4 | 4 | same |
| Working setpoint | 5 | 5 | same |
| Proportional band | 6 | 6 | same |
| Integral time | 8 | 8 | same |
| Derivative time | 9 | 9 | same |
| SP1 | 24 | 24 | same |
| SP2 | 25 | 25 | same |
| Local setpoint trim | 27 | 27 | same |
| Alarm 1 / 2 setpoints | 13 / 14 | 13 / 14 | same |
| Alarm 3 / 4 setpoints | 81 / 82 | 81 / 82 | same |
| Auto/manual | 273 | 273 | same |
| Autotune enable | 270 | 270 | same |
| Acknowledge all alarms | 274 | 274 | same |
| Instrument mode | 199 | 199 | same basic meaning |

This means a large part of a 3200-series driver can be reused for 2000-series instruments.

## 2. Important differences from 3200 series

### Protocols

2000 series supports:

- Modbus RTU
- JBUS, identical addressing to Modbus in this manual
- EI-Bisynch, Eurotherm’s older ASCII protocol

3200 series guide should normally use Modbus RTU only.

### Register resolution

2000-series Modbus uses 16-bit signed words:

- integer mode: values rounded to integers
- full-resolution mode: decimal place is implied by the instrument display configuration

2000 series also supports a special Modbus full-resolution floating-point area, unlike the simpler normal 3200 mapping.

### Remote setpoint difference

3200 series:

- frequent setpoint writes should use `REM.SP / AltSP` at address `26`.

2000 series:

- 2200 remote setpoint is address `26`
- 2400 remote setpoint comms-access parameter is address `26`
- 2400 remote setpoint in the SP list is address `485`

So a driver must identify whether it is controlling a 2200 or 2400 before assuming the remote-SP register.

### EEPROM risk

The manual explicitly warns that 2200 and 3200 instruments use EEPROM with a typical 100,000-change limit. For 2200
instruments, retained parameters are written to EEPROM whenever changed over comms, so avoid repeated writes to
setpoints, alarm levels, hysteresis, mode, timer, or programmer state.

## 3. Physical layer

Supported hardware:

- EIA232 / RS232
- EIA422 / 4-wire RS485
- EIA485 / 2-wire RS485

Use EIA485 for new multidrop installations where possible.

Typical 2-wire RS485 controller terminals:

- `HE` = A / A+ / receive
- `HF` = B / B+ / transmit
- `HD` = common

Network rules:

- daisy-chain instruments
- do not use star wiring
- use screened twisted pair
- connect screen to earth at one point
- use termination around 220 Ω at the end of the line if required
- device address range is `1–254`
- address `0` is broadcast write-only

## 4. Modbus RTU settings

Series 2000 supports RTU mode only, not Modbus ASCII.

Character format:

- 1 start bit
- 8 data bits
- parity: none, odd, or even
- 1 stop bit

Supported function codes:

- `01` / `02`: read bits
- `03` / `04`: read words
- `05`: write bit
- `06`: write word
- `07`: fast read status
- `08`: diagnostic loopback
- `16`: write multiple words

Recommended:

- use function `03` for reads
- use function `16` for writes, including Boolean/enumerated data

## 5. Core operating registers

| Function | Mnemonic | Modbus | Values |
| --- | ---: | ---: | --- |
| Process value | `PV` | 1 | read |
| Target setpoint | `SL` | 2 | read/write |
| Output power | `OP` | 3 | read/write in manual |
| Working output | `WO` | 4 | read |
| Working setpoint | `SP` | 5 | read |
| Auto/manual | `mA` | 273 | `0` auto, `1` manual |
| Instrument mode | `IM` | 199 | `0` normal, `1` standby, `2` configuration |
| Process error | `ER` | 39 | read |
| Controller version | `V0` | 107 | hex major/minor |
| Controller identifier | `II` | 122 | hex instrument ID |
| Communications address | `Ad` | 131 | read/write |

Recommended API:

```python
get_pv()
get_target_setpoint()
set_target_setpoint(value)
get_working_setpoint()
get_output()
set_manual_output(percent)
set_auto()
set_manual(percent)
set_standby(enabled)
read_instrument_id()
````

## 6. Setpoint registers

| Function            | 2400 Modbus |          2200 Modbus |
| ------------------- | ----------: | -------------------: |
| Select setpoint     |          15 |                   15 |
| Local/remote select |         276 |                  276 |
| SP1                 |          24 |                   24 |
| SP2                 |          25 |                   25 |
| SP3–SP16            |     164–177 | normally unavailable |
| Remote setpoint     |         485 |                   26 |
| Local trim          |          27 |                   27 |
| SP1 low/high limits |   112 / 111 |            112 / 111 |
| SP2 low/high limits |   114 / 113 |            114 / 113 |
| Setpoint rate limit |          35 |                   35 |
| Holdback type       |          70 |            2400 only |
| Holdback value      |          65 |            2400 only |

`L-r = 276`:

- `0`: local
- `1`: remote

## 7. PID and tuning

| Function                     |    Modbus |
| ---------------------------- | --------: |
| Autotune enable              |       270 |
| Adaptive tune enable         |       271 |
| Adaptive tune trigger level  |       100 |
| Automatic droop compensation |       272 |
| PB PID1                      |         6 |
| Integral time PID1           |         8 |
| Derivative time PID1         |         9 |
| Manual reset PID1            |        28 |
| Cutback high / low PID1      |   18 / 17 |
| Relative cool gain PID1      |        19 |
| PB PID2                      |        48 |
| Integral time PID2           |        49 |
| Derivative time PID2         |        51 |
| Manual reset PID2            |        50 |
| Cutback high / low PID2      | 118 / 117 |
| Relative cool gain PID2      |        52 |

High-level methods:

```python
configure_pid(pb, ti, td, reset=None, r2g=None, cb_low=None, cb_high=None)
start_autotune()
stop_autotune()
```

## 8. On/off and output control

| Function             |                     Modbus |
| -------------------- | -------------------------: |
| Heat hysteresis      |                         86 |
| Cool hysteresis      |                         88 |
| Heat/cool deadband   |                         16 |
| Sensor-break output  | 34 or 40 depending context |
| Output low limit     |                         31 |
| Output high limit    |                         30 |
| Output rate limit    |                         37 |
| Forced output level  |                         84 |
| Heat cycle time      |                         10 |
| Cool cycle time      |                         20 |
| Heat minimum on time |                         45 |
| Cool minimum on time |                         89 |

Manual/open-loop operation:

```python
write(273, 1)  # manual
write(3, output_percent)
```

Closed-loop operation:

```python
write(273, 0)  # auto
write(2, target_setpoint)
```

## 9. Alarms and status-related registers

| Function               | 2400 |            2200 |
| ---------------------- | ---: | --------------: |
| Alarm 1 setpoint       |   13 |              13 |
| Alarm 2 setpoint       |   14 |              14 |
| Alarm 3 setpoint       |   81 |              81 |
| Alarm 4 setpoint       |   82 |              82 |
| Alarm hysteresis 1     |   47 |             580 |
| Alarm hysteresis 2     |   68 |             580 |
| Alarm hysteresis 3     |   69 |             580 |
| Alarm hysteresis 4     |   71 |             580 |
| Loop break time        |   83 |              83 |
| Acknowledge all alarms |  274 |             274 |
| Sensor break status    |  258 |             258 |
| Loop break status      |  263 | varies by model |

Use status words rather than Modbus coils where possible.

## 10. Status words

### Main status word: address `75`

Important bits:

- bit 0: alarm 1
- bit 1: alarm 2
- bit 2: alarm 3
- bit 3: alarm 4
- bit 4: manual mode
- bit 5: sensor break
- bit 6: loop break
- bit 7: heater/load fault
- bit 8: tune active or load fail, model-dependent
- bit 9: ramp/program complete
- bit 10: PV out of range
- bit 13: remote input sensor break

### Control status word: address `76`

Important bits:

- bit 0: control algorithm freeze
- bit 1: PV input sensor broken
- bit 2: PV out of sensor range
- bit 3: self-tune failed
- bit 6: loop break
- bit 7: integral accumulator frozen
- bit 8: tune completed successfully
- bit 9: direct/reverse action
- bit 11: PID demand limited
- bit 15: manual/auto mode switch

### Instrument status word: address `77`

2400 only:

- bit 0: configuration/operation mode
- bit 2: setpoint-rate-limit ramp running
- bit 3: remote setpoint active
- bit 4: alarm acknowledge switch

## 11. Input configuration

Configuration parameters require instrument mode `199 = 2`.

| Function                       | Modbus |
| ------------------------------ | -----: |
| Input type                     |  12290 |
| CJC type                       |  12291 |
| Sensor break impedance         |  12301 |
| Input high                     |  12306 |
| Input low                      |  12307 |
| Displayed reading high         |  12302 |
| Displayed reading low          |  12303 |
| Range low                      |     11 |
| Range high                     |     12 |
| Input filter                   |    101 |
| PV offset / calibration offset |    141 |
| Comms PV / mV test value       |    203 |

Input type values differ from the 3200 series. Do not reuse 3200 enumerations blindly.

## 12. Programmer / ramp-dwell

2400 programmer registers:

| Function                |  Modbus |
| ----------------------- | ------: |
| Current program number  |      22 |
| Program status          |      23 |
| Programmer setpoint     |     163 |
| Cycles remaining        |      59 |
| Current segment number  |      56 |
| Current segment type    |      29 |
| Segment time remaining  |      36 |
| Segment target setpoint |     160 |
| Segment ramp rate       |     161 |
| Program time remaining  |      58 |
| Fast run                |      57 |
| Logic outputs 1–8       | 464–471 |
| Segment synchronisation |     488 |

Program status values:

- `1`: reset
- `2`: run
- `4`: hold
- `8`: holdback
- `16`: complete

Segment type:

- `0`: end
- `1`: ramp rate
- `2`: ramp time-to-target
- `3`: dwell
- `4`: step
- `5`: call

## 13. Configuration mode

To write configuration parameters:

```python
write(199, 2)  # enter configuration mode
```

Effects:

- normal control is disabled
- outputs go to a safe state
- no password is required
- with EI-Bisynch, address changes to `00`
- to exit, write `199 = 0`
- controller resets and is unavailable for about 5 seconds

Driver should guard configuration writes behind an explicit `allow_configuration=True` flag.

## 14. EI-Bisynch support

EI-Bisynch is optional for a driver unless legacy support is needed.

Key points:

- ASCII protocol
- 7 data bits, even parity, 1 stop bit
- addresses `01–99`; `00` reserved for configuration mode
- parameters addressed by mnemonics, e.g. `PV`, `OP`, `SL`, `mA`
- values returned in free text format, as displayed on the front panel
- hex format used for some status words

Recommended: implement Modbus first; add EI-Bisynch only for old installations.

## 15. Driver safety policy

A robust driver should:

1. Identify instrument type and version using addresses `107` and `122`.
2. Determine whether it is 2200 or 2400.
3. Use shared 3200-compatible addresses where possible.
4. Avoid repeated writes to retained values.
5. Decode status word `75` before enabling control.
6. Refuse closed-loop operation if sensor break, PV out-of-range, or loop break is active.
7. Use manual mode only after explicitly setting output limits.
8. Require explicit permission before entering configuration mode.
9. After leaving configuration mode, wait at least 5 seconds and reconnect.
10. Treat unconfigured parameters carefully: Modbus may return undefined values.

## 16. Minimal Python-style API

```python
class Eurotherm2000:
    def read_raw(address: int) -> int: ...
    def write_raw(address: int, value: int) -> None: ...

    def read_scaled(address: int) -> float: ...
    def write_scaled(address: int, value: float) -> None: ...

    def identify(self) -> dict: ...
    def get_pv(self) -> float: ...
    def get_setpoint(self) -> float: ...
    def set_setpoint(self, value: float) -> None: ...

    def get_output(self) -> float: ...
    def set_auto(self) -> None: ...
    def set_manual(self, output_percent: float) -> None: ...
    def set_standby(self, enabled: bool) -> None: ...

    def configure_pid(self, pb, ti, td, reset=None, r2g=None,
                      cb_low=None, cb_high=None) -> None: ...

    def start_autotune(self) -> None: ...
    def stop_autotune(self) -> None: ...

    def get_status(self) -> dict: ...
    def acknowledge_alarms(self) -> None: ...

    def enter_configuration(self) -> None: ...
    def exit_configuration(self) -> None: ...
```text

## 17. 3200-to-2000 porting notes

Can usually reuse:

- Modbus RTU transport
- signed 16-bit register handling
- PV/SP/output/mode register access
- PID register access
- alarm setpoint access
- auto/manual logic
- status-word decoding pattern

Must change or check:

- input type enumerations
- remote setpoint address, especially 2200 vs 2400
- programmer data layout
- configuration-mode behaviour
- EI-Bisynch support if needed
- EEPROM-write policy, especially for 2200

```

