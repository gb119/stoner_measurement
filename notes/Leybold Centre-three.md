# Leybold CENTER THREE RS232 Programming Guide

## 1. Interface

Use the rear-panel **RS232C** connector.

Serial settings:

```text
Protocol:       RS232C
Data bits:      8
Parity:         none
Stop bits:      1
Handshake:      none
Baud rates:     9600, 19200, 38400
Default baud:   9600
Encoding:       ASCII
Line ending:    CR or CR LF
```

The protocol uses three-character command mnemonics. Spaces in command strings are ignored.

Control characters:

```text
<ETX> 0x03  Ctrl-C  reset interface / clear input buffer
<ENQ> 0x05  Ctrl-E  request output-buffer contents
<ACK> 0x06          command accepted
<NAK> 0x15          command rejected
<CR>  0x0D
<LF>  0x0A
```

## 2. Transaction model

Most commands are query/set hybrid commands.

### Query

```text
Host:   CMD<CR>
Unit:   <ACK><CR><LF>
Host:   <ENQ>
Unit:   data<CR><LF>
```

### Set then read back

```text
Host:   CMD,param1,param2,...<CR>
Unit:   <ACK><CR><LF>
Host:   <ENQ>
Unit:   canonicalised_values<CR><LF>
```

### Write-only commands

Some commands, especially `SAV`, acknowledge only:

```text
Host:   SAV,1<CR>
Unit:   <ACK><CR><LF>
```

### Error handling

If a command is syntactically invalid:

```text
Host:   bad_command<CR>
Unit:   <NAK><CR><LF>
Host:   <ENQ>
Unit:   error_status<CR><LF>
```

Driver rule: after `NAK`, immediately send `<ENQ>` and parse the returned error status.

## 3. Number formats

Pressure, offset and threshold values are returned as exponential values:

```text
±a.aaaaE±aa
```

Example:

```text
1.2500E-01
```

Input may be either exponential or fixed point, for example `1.25E-1` or `0.125`.

Logarithmic gauges normally return only meaningful first mantissa digits; CTR linear gauges use full mantissa precision.

## 4. Channel and status conventions

Channel indices used in parameter commands are generally:

```text
0 = channel 1
1 = channel 2
2 = channel 3
```

Pressure status codes:

```text
0 = measurement data OK
1 = underrange
2 = overrange
3 = transmitter error
4 = transmitter switched off
5 = no transmitter
6 = identification error
7 = ITR error
```

Driver should expose both raw status and parsed state; do not return pressure as valid without checking status.

## 5. Continuous pressure streaming

After power-on, the unit continuously sends pressure measurements, by default once per second. This stream stops when the host sends any character. Resume it with `COM`.

```text
COM,a
```

`a`:

```text
0 = 100 ms
1 = 1 s
2 = 1 min
```

Response stream:

```text
s1,p1,s2,p2,s3,p3<CR><LF>
```

Recommended driver behaviour: disable or flush continuous mode during command transactions unless deliberately using streaming acquisition.

## 6. Core driver API mapping

### Identification and health

| Driver method             | Command | Response                                                                  |
| ------------------------- | ------: | ------------------------------------------------------------------------- |
| `get_firmware()`          |   `PNR` | firmware string, e.g. `302-533-F`                                         |
| `identify_transmitters()` |   `TID` | `TTR`, `TTR100`, `PTR`, `PTR 90`, `CTR`, `ITR`, `ITR200`, `noSen`, `noid` |
| `get_error_status()`      |   `ERR` | binary string: `0000`, `1000`, `0100`, `0010`, `0001`                     |
| `reset_interface()`       | `RES,1` | queued reset/error messages                                               |

`ERR` bits:

```text
1000 = device error
0100 = hardware not installed
0010 = invalid parameter
0001 = syntax error
```

`RES,1` queued error messages:

```text
0  = no error
1  = watchdog triggered
2  = task(s) not executed
3  = EPROM error
4  = RAM error
5  = EEPROM error
6  = display error
7  = A/D converter error
8  = UART error
9  = transmitter 1 general error
10 = transmitter 1 ID error
11 = transmitter 2 general error
12 = transmitter 2 ID error
13 = transmitter 3 general error
14 = transmitter 3 ID error
```

### Pressure reading

| Driver method              | Command | Notes                       |
| -------------------------- | ------: | --------------------------- |
| `read_pressure(channel=1)` |   `PR1` | returns `status,pressure`   |
| `read_pressure(channel=2)` |   `PR2` | analogous                   |
| `read_pressure(channel=3)` |   `PR3` | analogous                   |
| `read_all_pressures()`     |   `PRX` | returns `s1,p1,s2,p2,s3,p3` |
| `start_stream(period)`     | `COM,a` | starts continuous output    |

Pressure values are in the currently selected display unit.

### Units and display

| Driver method                                   |   Command | Values                                     |
| ----------------------------------------------- | --------: | ------------------------------------------ |
| `get_unit()` / `set_unit()`                     | `UNI[,a]` | `0=mbar/bar`, `1=Torr`, `2=Pa`, `3=Micron` |
| `get_display_digits()` / `set_display_digits()` | `DCD[,a]` | `2` or `3`                                 |
| `get_torr_lock()` / `set_torr_lock()`           | `TLC[,a]` | `0=off`, `1=on`                            |
| `get_parameter_lock()` / `set_parameter_lock()` | `LOC[,a]` | `0=off`, `1=on`                            |

### Serial configuration

```text
BAU[,a]
```

`a`:

```text
0 = 9600
1 = 19200
2 = 38400
```

Important: the acknowledgement to `BAU` is sent at the **new** baud rate. Driver should change the local serial port immediately after sending the command, before waiting for ACK.

### Saving settings

```text
SAV,0   restore/save default parameters
SAV,1   save current serial-interface parameter changes to EEPROM
```

Manual front-panel changes are saved automatically; serial changes require `SAV,1` if they must survive power cycling.

Avoid excessive EEPROM writes.

## 7. Sensor configuration commands

### Measurement filter

```text
FIL[,ch1,ch2,ch3]
```

Values:

```text
0 = fast
1 = medium/default
2 = slow
3 = CTR
```

### Gas type

```text
GAS[,ch1,ch2,ch3]
```

Values:

```text
0 = nitrogen/air
1 = argon
2 = hydrogen
3 = other gas
```

If `GAS=3`, use `COR` correction factors.

### Variable correction factor

```text
COR[,f1,f2,f3]
```

Each factor:

```text
0.10 … 9.99
default = 1.00
```

### Full-scale range for linear transmitters

```text
FSR[,ch1,ch2,ch3]
```

Values:

```text
0=0.01 mbar, 1=0.01 Torr, 2=0.02 Torr, 3=0.05 Torr,
4=0.10 mbar, 5=0.10 Torr, 6=0.25 mbar, 7=0.25 Torr,
8=0.50 mbar, 9=0.50 Torr, 10=1 mbar, 11=1 Torr,
12=2 mbar, 13=2 Torr, 14=5 mbar, 15=5 Torr,
16=10 mbar, 17=10 Torr, 18=20 mbar, 19=20 Torr,
20=50 mbar, 21=50 Torr, 22=100 mbar, 23=100 Torr,
24=200 mbar, 25=200 Torr, 26=500 mbar, 27=500 Torr,
28=1000 mbar, 29=1100 mbar, 30=1000 Torr,
31=2 bar, 32=5 bar, 33=10 bar, 34=50 bar,
35=DI200 mbar, 36=DI2 bar, 37=DI2 bar relative
```

### Offset correction for CTR/linear transmitters

```text
OFC[,ch1,ch2,ch3]
```

Values:

```text
0 = off
1 = on
2 = determine offset and activate correction
3 = adjust zero point of CTR100/CTR101
```

Offset values:

```text
OFD[,offset1,offset2,offset3]
```

Offsets are in the current pressure unit and use exponential format.

### Pirani range extension

```text
PRE[,ch1,ch2,ch3]
```

Values:

```text
0 = off
1 = on
```

### Degas

```text
DGS[,ch1,ch2,ch3]
```

Values:

```text
0 = degas off
1 = degas on
```

Degas automatically switches off after 3 minutes. Expose as a timed/unsafe operation in the driver.

### Emission mode

```text
EUM[,ch1,ch2,ch3]
```

Values:

```text
0 = manual
1 = automatic/default
```

### Filament selection

```text
FUM[,ch1,ch2,ch3]
```

Values:

```text
0 = automatic/default
1 = filament 1
2 = filament 2
```

### High-vacuum circuit

```text
HVC[,ch1,ch2,ch3]
```

Values:

```text
0 = off
1 = on
```

Only works when transmitter control is set to manual/hand.

### Transmitter control

For channel 1:

```text
SC1[,activation,deactivation,on_value,off_value]
```

Analogous:

```text
SC2
SC3
```

Activation mode:

```text
0 = manual/default
1 = hot start
2 = by channel 1
3 = by channel 2
4 = by channel 3
```

Deactivation mode:

```text
0 = manual/default
1 = self control
2 = by channel 1
3 = by channel 2
4 = by channel 3
```

Thresholds are in current pressure unit.

## 8. Switching functions / setpoints

CENTER THREE has six switching functions; CENTER TWO has four.

For setpoint 1:

```text
SP1[,assignment,lower_threshold,upper_threshold]
```

Analogous:

```text
SP2 … SP6
```

Assignment:

```text
0 = channel 1
1 = channel 2
2 = channel 3
```

Read switching function states:

```text
SPS
```

Response:

```text
sp1,sp2,sp3,sp4,sp5,sp6
```

Each state:

```text
0 = off
1 = on
```

Driver should validate that lower/upper thresholds are physically sensible and compatible with the selected gauge range.

## 9. Recorder / analogue output

Recorder output characteristic:

```text
AOM[,channel,curve]
```

Channel:

```text
0 = channel 1
1 = channel 2
2 = channel 3
```

Curve:

```text
0  = logarithmic LoG
1  = logarithmic LoG A
2  = logarithmic LoG -6
3  = logarithmic LoG -3
4  = logarithmic LoG +0
5  = logarithmic LoG +3
6  = logarithmic LoGC1
7  = logarithmic LoGC2
8  = logarithmic LoGC3
9  = linear Lin -10
10 = linear Lin -9
11 = linear Lin -8
12 = linear Lin -7
13 = linear Lin -6
14 = linear Lin -5
15 = linear Lin -4
16 = linear Lin -3
17 = linear Lin -2
18 = linear Lin -1
19 = linear Lin +0
20 = linear Lin +1
21 = linear Lin +2
22 = linear Lin +3
23 = iM221
24 = logarithmic LoGC4
25 = PM411
```

## 10. Error relay

```text
ERA[,a]
```

Values:

```text
0 = all errors
1 = device errors
2 = sensor 1 and device errors
3 = sensor 2 and device errors
4 = sensor 3 and device errors
```

## 11. Digital ITR/CTR data

```text
ITR
```

Returns raw 8-byte hexadecimal data strings for ITR/CTR100/CTR101 transmitters, separated by spaces between transmitters. Implement as a low-level raw method unless also implementing the referenced transmitter protocol.

## 12. Diagnostics and tests

Expose these separately from normal measurement APIs, with explicit safety warnings.

|      Command | Function                                      |
| -----------: | --------------------------------------------- |
|        `TAD` | read A/D converter values and ID voltages     |
|    `TDI[,a]` | display test, `0=off`, `1=on`                 |
|        `TEE` | EEPROM test; avoid loops                      |
|        `TEP` | EPROM test; returns error status and checksum |
| `TIO[,a,bb]` | relay test                                    |
|        `TKB` | keyboard test                                 |
|        `TRA` | RAM test                                      |
|        `TRS` | RS232 echo test; stop with Ctrl-C             |
|    `WDT[,a]` | watchdog acknowledgement mode                 |

Relay test `TIO`:

```text
a:
0 = off
1 = on

bb hexadecimal:
00 = all relays off
01 = SP1 relay on
02 = SP2 relay on
04 = SP3 relay on
08 = SP4 relay on
10 = SP5 relay on
20 = SP6 relay on
40 = error relay on
7F = all relays on
```

Do not run relay tests while external equipment is connected unless the caller explicitly confirms it.

## 13. Recommended driver structure

Implement a transport layer:

```python
send_command(cmd: str, params: list | None = None) -> None
query(cmd: str, params: list | None = None) -> str
parse_ack()
send_enq()
read_line()
```

Rules:

```text
1. Always terminate commands with CR.
2. Accept ACK CR LF and NAK CR LF.
3. On NAK, send ENQ and parse ERR-style status.
4. Strip CR/LF from data responses.
5. Split comma-separated values.
6. Convert pressure-like fields to float.
7. Preserve raw strings for firmware, transmitter IDs and hex diagnostic data.
8. Serialise access with a lock; the protocol has one output buffer.
9. Flush unsolicited continuous measurement lines before command/response transactions.
10. After changing baud rate, reconfigure the host port before reading ACK.
```

## 14. Minimum high-level driver methods

```text
connect()
disconnect()
reset_interface()
get_firmware()
get_error_status()
identify_transmitters()

read_pressure(channel)
read_all_pressures()
start_continuous(period)
stop_continuous_by_sending_command_or_ctrl_c()

get_unit()
set_unit(unit)
get_display_digits()
set_display_digits(digits)

get_filter()
set_filter(ch1, ch2, ch3)
get_gas()
set_gas(ch1, ch2, ch3)
get_correction_factor()
set_correction_factor(ch1, ch2, ch3)
get_full_scale_range()
set_full_scale_range(ch1, ch2, ch3)

get_offset_enabled()
set_offset_enabled(...)
determine_offset(channel)
set_offset_value(...)
get_offset_value()

get_degas()
set_degas(...)
get_emission_mode()
set_emission_mode(...)
get_filament()
set_filament(...)
get_hv_circuit()
set_hv_circuit(...)

get_sensor_control(channel)
set_sensor_control(channel, activation, deactivation, on_threshold, off_threshold)

get_setpoint(n)
set_setpoint(n, assignment, lower, upper)
get_setpoint_status()

get_recorder_output()
set_recorder_output(channel, curve)

save_user_parameters()
restore_default_parameters()

run_adc_test()
run_ram_test()
run_eprom_test()
run_eeprom_test()
run_keyboard_test()
run_relay_test(confirm=True)
```


The crucial difference is that the **DISPLAY THREE manual does not describe a serial/remote programming interface**. Unlike the CENTER THREE, which has an RS232C ACK/NAK command interface, the DISPLAY THREE is essentially a front-panel-configured gauge display with analogue outputs, relay outputs, and external HV-control inputs. A “fully featured driver” therefore cannot be command-based unless using external hardware to read analogue voltages and drive digital inputs.

# Leybold DISPLAY THREE LLM Driver Guide

## 1. Instrument scope

Models:

```text
DISPLAY TWO    230024    2 channels
DISPLAY THREE  230025    3 channels
Firmware/manual version: 2.1f
```

The DISPLAY THREE supports three measurement channels and six relay functions: two per channel. It is intended for THERMOVAC, PENNINGVAC and DU sensors.

## 2. Major difference from CENTER THREE

### CENTER THREE

```text
Has RS232C.
Supports ASCII 3-letter mnemonics.
Can be queried and configured by software.
```

### DISPLAY THREE

```text
No RS232C interface is documented.
No command mnemonics are documented.
No pressure query command exists.
No remote parameter read/write command exists.
Configuration is by front-panel buttons only.
Remote interaction is limited to:
  - analogue pressure outputs
  - relay contact outputs
  - external HV-control inputs for compatible PENNINGVAC transmitters
```

So a driver should be implemented as a **DAQ/digital-I/O integration driver**, not as a serial instrument driver.

## 3. Hardware I/O available to a driver

### Sensor inputs

Each channel uses an RJ45 sensor connector:

```text
1 +24 V DC
2 Power ground
3 Signal
4 Ident resistor
5 Signal ground
6 Status, PTR
7 HV on, PTR
8 not available
```

Only one transmitter should be connected per channel.

### Analogue pressure outputs

One analogue output per channel:

```text
Output range: 0–10 V or 0–5 V selectable
Output impedance: 100 Ω
Accuracy: ±0.1 % FS
Relationship: transmitter-dependent
```

Connector:

```text
1 CH1 analogue output
2 CH1 ground
3 CH2 analogue output
4 CH2 ground
5 CH3 analogue output
6 CH3 ground
```

Driver implication: pressure conversion must use the transmitter’s own voltage-to-pressure law, not a DISPLAY THREE command.

### HV-control inputs

For PTR225/PTR237 PENNINGVAC transmitters only:

```text
On  = +12 … +24 V DC
Off = 0 V DC
```

Connector:

```text
1 CH1 -
2 CH1 +12…24 V
3 CH2 -
4 CH2 +12…24 V
5 CH3 -
6 CH3 +12…24 V
```

Use this for external high-vacuum circuit control when the transmitter switch-on/off mode is configured for external control.

### Relay outputs

DISPLAY THREE has six relays: two per channel. Normally, relay 1 is a setpoint relay and relay 2 can be either a ready relay or a second setpoint relay. Relays are floating changeover contacts rated around 30 V AC/DC, 1 A.

## 4. Driver architecture

Recommended abstraction:

```text
DisplayThreeDriver
  ├── AnalogInputBackend
  │     read_voltage(channel)
  │     read_pressure(channel, transmitter_type)
  │
  ├── DigitalOutputBackend
  │     set_hv(channel, on)
  │
  ├── DigitalInputBackend
  │     read_setpoint_relay(channel, relay=1|2)
  │     read_ready_relay(channel)
  │
  └── ConfigurationRecord
        stores manually configured DISPLAY THREE parameters
```

The driver should not pretend to read internal settings from the instrument. Store configuration in software only after the operator has set matching values on the front panel.

## 5. Supported transmitters

```text
THERMOVAC:
  TTR90, TTR90S, TTR91, TTR91S, TTR96,
  TTR211S, TTR216S

THERMOVAC:
  TTR100, TTR100S2, TTR101, TTR101S2

PENNINGVAC:
  PTR225, PTR225S, PTR237, PTR90

DU sensors:
  DU200, DU201, DU2000, DU2001
```

Compared with CENTER THREE, DISPLAY THREE supports fewer sensor families: it omits CERAVAC/CTR and IONIVAC/ITR support described for the CENTER controller.

## 6. Front-panel parameters to mirror in software

These are not remotely programmable; the driver should track them as expected/manual configuration.

### Switching functions

Per channel:

```text
SP1-Lo
SP1-Hi
SP2-Lo
SP2-Hi   only if ready function disabled
```

Behaviour:

```text
pressure < lower threshold  -> relay energised
pressure > upper threshold  -> relay de-energised
between thresholds          -> previous state retained
```

Threshold range is sensor-dependent, generally `1e3 … 1e-12 mbar`, with at least 10% hysteresis.

### Sensor parameters

```text
PrE     Pirani range extension: off/on
FiLt    filter: 1, 3, 7, 15
rEAdY   second relay mode: ready / setpoint
Cor     gas correction factor, PTR225/PTR237 only, 0.1 … 9.9
S-on    transmitter switch-on mode
t-on    switch-on threshold, if channel-controlled
S-oFF   transmitter switch-off mode
t-off   switch-off threshold, if channel-controlled
```

Filter affects display and switching functions, but not analogue outputs.

### PENNINGVAC switch-on modes

```text
HAnd   manual front-panel UP key
ECt    external optocoupler input, +12…24 V DC
Hot    warm start on power-up
CH 1   switch on when channel 1 pressure falls below t-on
CH 2   switch on when channel 2 pressure falls below t-on
CH 3   switch on when channel 3 pressure falls below t-on; DISPLAY THREE only
```

### PENNINGVAC switch-off modes

```text
HAnd   manual front-panel DOWN key
ECt    external optocoupler input
SELF   self-monitoring; off when own pressure exceeds t-off
CH 1   off when channel 1 exceeds t-off
CH 2   off when channel 2 exceeds t-off
CH 3   off when channel 3 exceeds t-off; DISPLAY THREE only
```



## 7. General parameters

```text
unit:
  mbar
  Torr
  Pa

diGit:
  2 digits
  3 digits

bri:
  Hi
  Lo

AnALoG:
  Hi  analogue output same as sensor output
  Lo  halved analogue output
```

Factory defaults include `PrE=oFF`, `FiLt=3`, `rEAdY=on`, `Cor=1.00`, `S-on=HAnd`, `S-oFF=HAnd`, unit `mbar`, `diGit=2`, brightness `Hi`, analogue output `Hi`.

## 8. Driver methods to implement

```python
read_voltage(channel) -> float
read_pressure(channel, transmitter_model) -> float
read_all_pressures() -> dict[int, float]

set_hv(channel, enabled) -> None
get_hv_output_state(channel) -> bool  # software state only, unless feedback wired

read_setpoint_state(channel, relay=1) -> bool
read_ready_state(channel) -> bool

configure_expected_channel(
    channel,
    transmitter_model,
    unit="mbar",
    analog_mode="Hi",
    gas_correction=1.0,
    filter_value=3,
)

convert_voltage_to_pressure(channel, voltage, transmitter_model) -> float
```

Do **not** implement:

```text
get_firmware()
serial_query()
set_unit()
set_filter()
set_setpoint()
identify_transmitters()
```

unless additional hardware or undocumented protocol information is available.

## 9. Similarities to CENTER THREE

Same/similar concepts:

```text
DISPLAY THREE ≈ CENTER THREE, conceptually:
  - 3-channel gauge display
  - DISPLAY TWO / CENTER TWO are 2-channel variants
  - same broad THERMOVAC/PENNINGVAC architecture
  - pressure display in mbar/Pa/Torr
  - switching thresholds with hysteresis
  - Pirani range extension
  - gas correction factor
  - high-vacuum circuit control for PENNINGVAC
  - analogue outputs
  - front-panel parameter groups: SP, SEn, GEn
```

Key differences:

```text
CENTER THREE:
  - RS232C remote command interface
  - richer transmitter support: includes CERAVAC/CTR and IONIVAC/ITR
  - programmable recorder output
  - software-readable pressure/status/error information
  - remote setpoint and parameter programming

DISPLAY THREE:
  - no documented RS232C or command interface
  - analogue/digital external I/O only
  - fewer transmitter families
  - one analogue output per channel only
  - parameters are front-panel configured and auto-saved to EEPROM
```

Final implementation recommendation: treat the DISPLAY THREE as a **passive gauge display plus I/O breakout**, while treating the CENTER THREE as a **true programmable controller**.


Yes. The Edwards TIC is closer to the **Leybold CENTER THREE** than the **DISPLAY THREE**, because it has a documented serial protocol. It is more object-oriented than Leybold’s three-letter mnemonic interface.

# Edwards TIC LLM Coding-Agent Guide

## 1. Instrument family

Applies to Edwards TIC serial-controlled units:

```text
D39700000  TIC Instrument Controller
D39701000  TIC Instrument Controller 6-Gauge
D39702000  TIC Instrument Controller 6-Gauge Capacitance Manometer
D39711000  TIC Turbo Controller 100 W
D39712000  TIC Turbo Controller 200 W
D39721000  TIC Turbo & Instrument Controller 100 W
D39722000  TIC Turbo & Instrument Controller 200 W
```

## 2. Protocol model

The TIC is a **master/slave ASCII serial device**. The PC always initiates a transaction and must wait for the reply before sending another message. Messages end with carriage return. Queries begin with `?`; commands begin with `!`. Responses contain either data, beginning with `=`, or command status, beginning with `*`.

Basic forms:

```text
Query value:     ?V<object_id><CR>
Query setup:     ?S<object_id><CR>
Command:         !C<object_id> <value><CR>
Write setup:     !S<object_id> <config_or_data><CR>
```

Examples:

```text
?V913<CR>          read gauge 1 value
?S902<CR>          read system identification string
!C904 1<CR>        turbo pump on
!C904 0<CR>        turbo pump off
!C916 1<CR>        relay 1 on
!C916 0<CR>        relay 1 off
```

Typical timeout:

```text
normal messages:       <100 ms
pump-routed messages:  <200 ms
recommended timeout:   500 ms
turbo upload:          <2 s
turbo download:        <4 s
```

## 3. Optional multi-drop prefix

In multi-drop mode, prefix messages with:

```text
#<destination_id>:<source_id>
```

The TIC accepts wildcard multi-drop address `99`. It also accepts wildcard object ID `0` for `?S`, returning TIC status object `902`.

## 4. Response parsing

Command status codes:

```text
0 = no error
1 = invalid command for object ID
2 = invalid query/command
3 = missing parameter
4 = parameter out of range
5 = invalid command in current state
6 = data checksum error
7 = EEPROM read/write error
8 = operation took too long
9 = invalid config ID
```

Priority:

```text
0 = OK
1 = warning
2/3 = alarm
```

Driver rule: a `*... 0` response only means the command was accepted by the serial layer. For configuration writes, read the setup back and verify it.

## 5. Core object IDs

### System and identification

```text
901  Node / multidrop address
902  TIC status and system string
929  Display pressure units
930  PC comms RS232/RS485
931  Default screen
932  Fixed/float ASG display
933  System on/off setup and command
```

System string:

```text
?S902
=> TIC;software_version;serial_number;PIC_software_version
```

Pressure units:

```text
?S929
!S929 1   kPa
!S929 2   mbar
!S929 3   Torr
```

## 6. Gauge API

Gauge objects:

```text
913  Gauge 1
914  Gauge 2
915  Gauge 3
934  Gauge 4
935  Gauge 5
936  Gauge 6
940  All gauge values
```

Read one gauge:

```text
?V913
=> value;units_type;state;alert_id;priority
```

Read all connected gauges:

```text
?V940
=> position;value;position;value;...
```

Special value:

```text
9.9000e+09  gauge not ON / error / striking / unavailable
```

Gauge setup supports setpoint linkage, gauge type, gas type, filter on/off, ASG range, user gauge name, CapMan range, and IGC setup depending on gauge model. Gauge commands include accept new gauge, on/off, zero, calibrate and degas.

Gauge type constants include:

```text
0  Unknown Device
1  No Device
7  APGM
8  APGL
9  APGXM
10 APGXH
11 APGXL
15 WRG
16 AIMC
17 AIMN
18 AIMS
19 AIMX
25 ASG
```

Gas constants:

```text
0 Nitrogen
1 Helium
2 Argon
3 Carbon Dioxide
4 Neon
5 Krypton
6 Voltage
```



## 7. Turbo pump API

Turbo-related objects:

```text
904  Turbo pump state / on-off / type / setup
905  Turbo speed
906  Turbo power
907  Turbo normal-speed flag
908  Turbo standby
909  Turbo cycle time
```

Commands:

```text
!C904 1   turbo on
!C904 0   turbo off
!C908 1   standby on
!C908 0   standby off
```

Read values:

```text
?V904  state;alert_id;priority
?V905  speed_percent;alert_id;priority
?V906  power_watts;alert_id;priority
?V907  4 = normal speed, 0 = not normal
?V909  hours_on;state;alert_id;priority
```

Full pump states include stopped, starting delay, accelerating, running, stopping delays, fault braking and braking.

## 8. Backing pump and auxiliaries

```text
910  Backing pump
911  Backing speed
912  Backing power
919  Power-supply temperature
920  Internal temperature
921  Analogue output
922  External vent valve
923  Heater band
924  External air cooler
925  Display contrast
926  Configuration operations
928  Lock / unlock configuration and front panel
```

Examples:

```text
?V910       backing pump state
!C910 1     backing pump on
!C910 0     backing pump off

?V923       heater band time/state
!C923 1     heater band on
!C923 0     heater band off
```

## 9. Relay API

Relay objects:

```text
916  Relay 1
917  Relay 2
918  Relay 3
937  Relay 4
938  Relay 5
939  Relay 6
```

Read relay state:

```text
?V916
=> state;alert_id;priority
```

Set relay manually:

```text
!C916 1
!C916 0
```

Relay setup follows the common slave setup model:

```text
master_object;units_type;on_setpoint;off_setpoint;enable
```

Units types include pressure, voltage and speed modes.

## 10. Recommended Edwards driver methods

```python
connect()
disconnect()
query_value(object_id)
query_setup(object_id, config_type=None)
write_setup(object_id, *fields)
command(object_id, value)

get_identity()
get_system_status()
get_pressure_units()
set_pressure_units(unit)

read_gauge(channel)
read_all_gauges()
get_gauge_type(channel)
set_gauge_filter(channel, enabled)
set_gauge_gas(channel, gas)
zero_gauge(channel)
calibrate_gauge(channel)
degas_gauge(channel)

turbo_on()
turbo_off()
get_turbo_state()
get_turbo_speed()
get_turbo_power()
set_turbo_standby(enabled)

backing_on()
backing_off()
get_backing_state()

read_relay(n)
set_relay(n, enabled)
configure_relay(n, source, units, on_setpoint, off_setpoint, enabled)

get_internal_temperature()
get_power_supply_temperature()
set_display_contrast(value)
lock_front_panel()
unlock_front_panel()
```

# Shared API design across the three instruments

## Common high-level abstraction

Use a common interface like this:

```python
class VacuumController:
    def identify(self) -> DeviceInfo: ...
    def read_pressure(self, channel: int) -> PressureReading: ...
    def read_all_pressures(self) -> dict[int, PressureReading]: ...
    def get_gauge_type(self, channel: int) -> str | None: ...
    def set_gauge_on(self, channel: int, enabled: bool) -> None: ...
    def zero_gauge(self, channel: int) -> None: ...
    def degas_gauge(self, channel: int, enabled: bool) -> None: ...
    def get_setpoint(self, index: int) -> Setpoint: ...
    def set_setpoint(self, index: int, setpoint: Setpoint) -> None: ...
    def read_relay(self, index: int) -> RelayState: ...
    def set_relay(self, index: int, enabled: bool) -> None: ...
```

## Capability matrix

```text
Feature                         CENTER THREE     DISPLAY THREE     Edwards TIC
Serial pressure read            Yes              No               Yes
Remote parameter setup          Yes              No               Yes
Analogue outputs                Yes              Yes              Yes / configurable
Relay/setpoint outputs          Yes              Yes              Yes
Gauge identification            Yes              Front-panel only Yes
Gauge zero/degas/control        Partial/yes       Front-panel/HV   Yes
Pump control                    No turbo object   No               Yes
Multi-gauge support             3 channels        3 channels       3 or 6 channels
Best driver type                Serial driver     DAQ/I/O driver   Serial object driver
```

## Recommended shared data classes

```python
@dataclass
class PressureReading:
    channel: int
    value: float | None
    unit: str
    status: str
    raw_status: int | str | None = None
    alert_id: int | None = None
    priority: int | None = None

@dataclass
class Setpoint:
    source_channel: int | None
    lower: float
    upper: float
    unit: str
    enabled: bool = True

@dataclass
class RelayState:
    index: int
    state: bool | None
    raw_state: int | str
    alert_id: int | None = None
    priority: int | None = None

@dataclass
class DeviceCapabilities:
    serial: bool
    pressure_query: bool
    remote_setpoints: bool
    remote_gauge_control: bool
    pump_control: bool
    analogue_only: bool
    max_channels: int
    max_relays: int
```

## Backend separation

Use three protocol backends under one public API:

```text
LeyboldCenterBackend
  transport: RS232 ACK/NAK + ENQ
  commands: PR1/PR2/PR3/PRX, SP1-SP6, TID, PNR, etc.

LeyboldDisplayBackend
  transport: DAQ analogue input + digital I/O
  commands: none documented
  configuration: operator-entered mirror state

EdwardsTICBackend
  transport: ASCII object protocol
  commands: ?V, ?S, !C, !S with object IDs
```

## Key design rule

The public API should be **capability-driven**, not model-driven. For example, `read_pressure(1)` should work for all three, but internally:

```text
CENTER THREE   -> PR1 serial query
DISPLAY THREE  -> read analogue voltage and convert externally
Edwards TIC    -> ?V913 object query
```

This lets experimental-control code use one abstraction while still respecting the very different transport layers.
