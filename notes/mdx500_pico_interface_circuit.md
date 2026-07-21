# MDX 500 Raspberry Pi Pico interface: reference circuit

## Status and design intent

This is a **prototype reference design for a controller/backplane and up to
eight plug-in MDX 500 channel cards**, not a certified machine-safety circuit.
It translates a PCB-mounted Raspberry Pi Pico's 3.3 V SPI/GPIO signals into
the MDX 500 User-port signals needed for setpoint, regulation-mode, on/off, and
monitoring. Repeat the isolated channel card once per MDX; do not join User-port
grounds from different supplies until measurements and the installation wiring
prove that they are intended to be common.

The MDX's genuine vacuum, water, and main interlocks remain hard-wired to pins
4, 5, and 6. The Pico board must not satisfy or bypass them.

## Electrical architecture

```text
USB / Pico domain                    reinforced isolation       one MDX field domain

Pico 3.3 V SPI -------------------- ADuM4151 ------------------ AD5754R 0-10 V DAC
        GPIO ---------------------- MOSFET relays ------------- active-low controls
        GPIO <--------------------- optocouplers -------------- active-low status
                                                             + ADS8688 0-10.24 V ADC
                                                             + regulators from pin 14
```

The analog converters are referenced to the MDX User-port ground. Galvanic
isolation is placed in the SPI connection, so no MDX ground reaches the Pico or
USB host. The three command contacts use normally-open MOSFET relays; loss of
Pico power opens every contact and therefore removes the remote-on command.

## Modular eight-channel system architecture

The intended construction is one controller/backplane PCB with the Pico mounted
directly on it, plus one plug-in isolated card for each MDX. There is no cable
between the Pico and the backplane SPI logic. A keyed board-to-board connector
or short backplane trace connects each channel card to the controller domain.

```text
PCB-mounted Pico
   |
   +-- shared buffered SCLK/MOSI -------------------------+-- slot 0 ADuM4151
   |                                                      +-- slot 1 ADuM4151
   |                                                      +-- ...
   |                                                      +-- slot 7 ADuM4151
   +-- A2:A0 + ADC/DAC enables --> two 3-to-8 decoders --> per-slot chip selects
   +<---------------- SN74HC151 8-to-1 multiplexer <------ per-slot ADuM MI outputs
   +-- 74HC595 chain + common latch ---------------------> 24 relay commands
   +<-- 74HC165 chain ------------------------------------ 16 status inputs
   +-- hardware output permit/watchdog ------------------> all REMOTE_ON paths
```

SCLK and MOSI can be shared because they are inputs at every isolator. The
controller-side `MI` outputs of multiple ADuM4151 devices are push-pull and
**must not be wired together**. `U103=SN74HC151` selects exactly one channel's
MISO return using the same `SLOT_A[2:0]` address presented to the chip-select
decoders.

Use `U101/U102=SN74HC138` active-low decoders for the eight ADC and eight DAC
chip-select lines. Firmware must keep both decoder enables inactive while
changing the slot address, wait for address/decoder settling, and then enable
exactly one decoder. The DAC-select path uses the ADuM4151 auxiliary channel and
therefore must respect its slower pulse-width and propagation specifications.
Start commissioning at 500 kHz SPI and do not exceed 1 MHz without backplane
signal-integrity measurements.

Use `U100=SN74LVC244A` as a source-side fan-out buffer: four outputs distribute
SCLK to two slots each and four distribute MOSI to two slots each. Fit one
source-series resistor per buffer output. This prevents eight cards and their
connectors from appearing as one large unterminated load.

### Relay and status expansion

Three cascaded `U110-U112=74HC595` registers provide 24 persistent relay bits:

```text
bit 3*n + 0 = channel n REMOTE_ON
bit 3*n + 1 = channel n MODE_P
bit 3*n + 2 = channel n MODE_I
```

All 24 bits update on one common `RELAY_LATCH` edge. Pull `OE_N` high so the
outputs are disabled during reset, and fit pull resistors that leave every
relay LED off while outputs are high impedance. Firmware first shifts a complete
shadow bitmap and then pulses the latch; it must never perform read-modify-write
operations directly against unknown hardware state.

Two cascaded `U120/U121=74HC165` registers acquire the 16 status bits atomically:

```text
bit 2*n + 0 = channel n SETPOINT_OK
bit 2*n + 1 = channel n OUTPUT_ON
```

A controller-independent watchdog/output-permit circuit must remove current
from all eight `REMOTE_ON` relay LEDs if the Pico stops servicing the watchdog,
resets, or loses power. Mode contacts may retain their last state because the
remote-on contacts have opened. This watchdog is a supervisory layer and is not
a substitute for the MDX interlocks or an emergency-off circuit.

### Atomic multi-gun trigger

Setpoints and mode contacts are prepared while all selected `REMOTE_ON` contacts
are open. A group trigger changes the desired `REMOTE_ON` bits in the 74HC595
shadow word, shifts the complete 24-bit word, and applies one latch edge. The
relay commands therefore change together; expected electrical skew is dominated
by the individual MOSFET-relay turn-on times and should remain far below 100 ms.

The hardware trigger sequence is:

1. Write and verify every selected channel's mode and DAC setpoint.
2. Confirm all selected channels remain output-off and the watchdog permit is
   valid.
3. Shift the new relay bitmap without changing the latch outputs.
4. Record the trigger timestamp and pulse `RELAY_LATCH` once.
5. Temporarily monitor the igniting channels at approximately 100 Hz; return to
   10 Hz per running channel after ignition has settled.

If synchronized deposition matters more than synchronized plasma ignition,
ignite and stabilize the guns behind closed shutters and use a separate common
shutter trigger as the deposition-time origin. Magnetron ignition latency can
vary even when the electrical start commands are simultaneous.

## Channel-card sheet 1: connectors, power, and isolated SPI

### Connectors

- `J1`: keyed channel-card/backplane connector: `3V3_CTL`, `GND_CTL`, `SCLK`, `MOSI`, `MISO`,
  `ADC_CS_N`, `DAC_CS_N`, `AFE_RESET_N`, `REMOTE_ON`, `MODE_P`, `MODE_I`,
  `SETPOINT_OK`, and `OUTPUT_ON`.
- `J2`: male DB-25 plug to mate with the MDX female User port. Connect the
  shell to chassis at the connector. Use pins 20/21 for the analog return and
  pin 25 for the field/control return, joined at one local `GND_MDX` star point.

### Field-side rails

1. `J2.14 (+15V_AUX)` -> `F1`, 63 mA fast fuse -> `+15V_F`. The fuse is
   secondary protection, not a precise current limiter; the normal design load
   must remain far below the MDX pin's 100 mA rating.
2. Provide a **DNP-only** footprint for `D1`, a low-leakage transient clamp,
   from `+15V_F` to `GND_MDX`. Populate it only after the actual auxiliary-rail
   source impedance and clamp current have been measured. Add `C1=10 uF` and
   `C2=100 nF` locally.
3. `U1=TPS7A4901` generates `+5V_F` from `+15V_F`. Set its feedback divider
   for 5.0 V and use the input, output, noise-reduction, and enable components
   from the current data-sheet application circuit. This 36 V-input part gives
   useful margin above the nominal 15 V auxiliary rail.
4. `U8=TPS7A4901` generates `+12V_A` from `+15V_F` for the DAC analog supply.
   Regulating this rail avoids operating the DAC close to its 16.5 V maximum
   recommended supply when the nominal 15 V auxiliary rail is high or noisy.
5. `U2=TLV75533P` generates `+3V3_F` from `+5V_F`, with 1 uF minimum ceramic
   input/output capacitors (use 4.7 uF in the prototype).
6. Budget less than 50 mA from pin 14, leaving at least a factor-of-two margin
   below its 100 mA rating. Measure the assembled board before connection.

### SPI barrier

Use `U3=ADuM4151ARIZ`, powered by `3V3_CTL/GND_CTL` on side 1 and
`+3V3_F/GND_MDX` on side 2. Fit 100 nF plus 1 uF at each supply pair.

| Pico-side net | ADuM4151 function | Field-side net |
|---|---|---|
| `SCLK` | `MCLK -> SCLK` | shared ADC/DAC clock |
| `MOSI` | `MO -> SI` | shared ADC/DAC data in |
| `MISO` | `MI <- SO` | shared tri-stated data out |
| `ADC_CS_N` | `MSS -> SSS` | `U5.CS_N` |
| `DAC_CS_N` | `VIA -> VOA` | `U4.SYNC_N` |
| `AFE_RESET_N` | `VIB -> VOB` | `U4.CLR_N` and `U5.RST_PD_N` |

Fit `R30/R31/R32=33 ohm` in series with field-side SCLK, MOSI, and MISO close to
the isolator. Pull both chip-select nets high with 10 kohm. Pull
`AFE_RESET_N` low with 10 kohm so the DAC is cleared and ADC is held in reset
while the field-side logic is unpowered or starting. Confirm the selected
ADuM4151 ordering-code fail-safe output state before PCB release.

## Channel-card sheet 2: analog setpoint output

Use `U4=AD5754R`, powered as a single-supply unipolar DAC:

- `AVDD = +12V_A`, `AVSS = GND_MDX`, `DVCC = +3V3_F`.
- Join `GND`, `DAC_GND_A..D`, and `SIG_GND_A..D` to the quiet analog star at
  DB-25 pin 21. Connect the exposed pad as required by the data sheet.
- Use the internal reference; decouple `REFIN/REFOUT`, AVDD, and DVCC exactly
  as the data sheet recommends.
- Tie `LDAC_N` low for update on the rising edge of `SYNC_N`.
- Drive `CLR_N` from `AFE_RESET_N`. Configure clear-to-zero and power down
  unused channels B-D.
- Configure channel A for `0..10 V` on a 10 V-option MDX or `0..5 V` on a
  5 V-option MDX. Make this an installation setting; never infer it from the
  requested power.

The output connection is:

```text
U4.VOUTA ---- R20 100 ohm ----+---- J2.23 LEVEL_IN
                              |
                             C20 10 nF C0G
                              |
                         J2.21 / GND_MDX
```

`R20/C20` is an EMI filter, not a scaling divider. Include footprints for an
optional low-leakage clamp but do not populate it until its leakage and clamp
error have been checked. Use a twisted/shielded pair for pins 23 and 21. Route
this trace away from the isolator, relay LED currents, and the magnetron cable.

DAC transfer functions:

```text
code = round(65535 * requested_engineering_value / full_scale_engineering_value)
power mode:   full_scale_engineering_value = 500 W
voltage mode: full_scale_engineering_value = 1200 V
current mode: full_scale_engineering_value = 1 A (for the documented low tap)
```

The firmware must write a zero code before it is allowed to close the remote-on
contact.

## Channel-card sheet 3: analog monitors

Use `U5=ADS8688` with `AVDD=+5V_F`, `DVDD=+3V3_F`, internal 4.096 V reference,
and each used input programmed for the unipolar `0..10.24 V` range. Follow the
data sheet's reference-capacitor and supply-decoupling layout exactly.

| ADC input | MDX pin | Signal | Engineering full scale |
|---|---:|---|---:|
| `AIN0` | 1 | current monitor | 1 A |
| `AIN1` | 2 | power monitor | 500 W |
| `AIN2` | 3 | voltage monitor | 1200 V |
| `AIN3` | 12 | programmed level monitor | selected mode full scale |

For each channel use:

```text
MDX monitor ---- 1.00 kohm, 0.1% ----+---- AINnP
                                      |
                                    100 nF C0G/film
                                      |
corresponding MDX analog ground ----------- AINnGND
```

The 1 kohm resistor and ADS8688's nominal 1 Mohm input produce about 0.1%
gain loss, which should be removed in per-channel calibration. The approximate
filter corner is 1.6 kHz; additional averaging should be digital. Place the
resistors at the connector and capacitors at the ADC. Power down or ignore the
unused channels.

## Channel-card sheet 4: remote control and status

Use three `G3VM-61G1` normally-open MOSFET relays. The corresponding backplane
74HC595 output drives each relay LED through
`R=(3.3 V - measured VF) / 5 mA`; `430 ohm` is the initial value for
approximately 5 mA with a 1.15 V LED. The common hardware output-permit must
gate the `REMOTE_ON` LED path. Confirm logic-output current limits and the actual
relay LED drop.

| Relay | Contact wiring | Meaning when closed |
|---|---|---|
| `K1 REMOTE_ON` | J2.7 and J2.8 tied together -> K1 -> J2.25 | two-wire remote output on |
| `K2 MODE_P` | J2.16 -> K2 -> J2.25 | `P_REG_N = low` |
| `K3 MODE_I` | J2.17 -> K3 -> J2.25 | `I_REG_N = low` |

Mode contact truth table:

| Requested mode | K2 / pin 16 | K3 / pin 17 |
|---|---|---|
| voltage | closed / low | closed / low |
| power | closed / low | open / high |
| current | open / high | closed / low |

Never change K2/K3 while K1 is closed. On boot: K1 open, write DAC zero, select
mode, verify status, then permit K1 to close. On any exception: open K1 first,
then clear the DAC.

For status, use two high-CTR phototransistors (`U6/U7`, for example LTV-817C):

```text
J2.14 +15V_AUX -- 6.8 kohm --|>|-- J2.13 SETPOINT_OK_N
J2.14 +15V_AUX -- 6.8 kohm --|>|-- J2.22 OUTPUT_ON_N

Pico side of each optocoupler:
3V3_CTL -- 10 kohm --+-- Pico input
                     |
                 collector
                 emitter -- GND_CTL
```

The MDX lines sink current when true, so the optocoupler transistor turns on
and the Pico input reads low. Each LED current is approximately 2 mA. Firmware
should expose logical `setpoint_ok` and `output_on` values after inversion and
debouncing. These two controller-side signals return through the channel-card
connector to the 74HC165 status chain.

## DB-25 connections used by this board

| Pin | Connection |
|---:|---|
| 1 | ADS8688 AIN0 through filter |
| 2 | ADS8688 AIN1 through filter |
| 3 | ADS8688 AIN2 through filter |
| 4, 5, 6 | no PCB control; remain in genuine hardware interlock chain |
| 7, 8 | tied locally and switched to pin 25 by K1 |
| 9, 20, 21, 25 | field ground/star; retain separate routing to star |
| 10 | test point only; do not parallel with the DAC reference |
| 12 | ADS8688 AIN3 through filter |
| 13 | active-low status optocoupler |
| 14 | fused field-side power and status-LED source |
| 16 | switched to pin 25 by K2 |
| 17 | switched to pin 25 by K3 |
| 22 | active-low status optocoupler |
| 23 | AD5754R channel-A output through EMI filter |

## Layout constraints

- Maintain the ADuM4151 data-sheet creepage/clearance keep-out; no copper,
  pours, test points, or silkscreen crossings under the isolation gap.
- Use separate `GND_CTL` and `GND_MDX` zones. Join MDX analog/digital returns
  only at the DB-25 star point; never bridge to USB shield.
- Put the DB-25, filters, MOSFET relays, and status optocouplers at the board
  edge. Keep the DAC/ADC close to their connector filters.
- Give ADC reference and DAC reference/ground loops their own quiet routing.
- Place every 100 nF decoupler directly at its IC supply pins with the smallest
  loop possible; add one local bulk capacitor per rail.
- Treat the enclosure and cable shield as an EMC design problem. Bond the DB-25
  shell to the metal enclosure at entry, not through a long PCB ground trace.
- Keep the Pico and all backplane multiplexing/shift-register logic entirely in
  the `GND_CTL` domain. No backplane trace may bridge an ADuM isolation keep-out.
- Route buffered SCLK/MOSI as short point-to-few-point nets. Keep the unbuffered
  Pico-side source nets local to U100 and give every slot a continuous
  controller-ground return adjacent to its digital signals.

## Pre-connection checks

1. Confirm whether the specific MDX is the 5 V or 10 V analog option.
2. With J2 disconnected, verify isolation resistance between `GND_CTL` and
   `GND_MDX` and inspect creepage/clearance.
3. Power the field side from a current-limited 15 V bench supply; verify rail
   voltages and total current.
4. Sweep DAC codes and measure pin 23 test output at 0%, 25%, 50%, 75%, and
   100%; test power-up, Pico reset, and cable-disconnect behavior.
5. Inject known 0-10 V signals into all ADC channels and calibrate gain/offset.
6. Verify every MOSFET relay is open with Pico power removed. Check the mode
   truth table by continuity, not only firmware state.
7. Simulate the two active-low status outputs with current-limited switches.
8. First MDX test: output disconnected from the process, genuine interlocks
   active, setpoint zero, remote-on open. Have a physical emergency-off path.

## Parts that require final data-sheet review

- AD5754R range programming, clear-code selection, power-up sequence,
  capacitive-load stability, and decoupling.
- ADS8688 reference capacitors, input-ground limits, SPI timing, and reset
  behavior.
- ADuM4151 ordering-code default outputs and isolation-layout rules.
- TPS7A4901 feedback, stability, enable, noise-reduction, and thermal design.
- G3VM-61G1 input current across temperature and contact leakage.

These reviews, plus an independent schematic/ERC review, are gates before a
PCB is ordered or an MDX output is enabled.

## Full prototype parts list

The first part of this bill of materials is for **one complete isolated MDX
channel card** and must be multiplied by the number of fitted supplies. The
later controller/backplane list is required once for a system of up to eight
channels.
Manufacturer ordering codes are given for the specialised parts; ordinary
passives may be sourced from any reputable manufacturer that meets the stated
dielectric, tolerance, voltage, and temperature requirements.

Items marked **provisional** require schematic/thermal review. Items marked
**DNP** have a PCB footprint but are not fitted to the first prototype.

### Integrated circuits and isolation devices

| References | Qty | Part / suggested ordering code | Package | Function and selection notes |
|---|---:|---|---|---|
| U1 | 1 | TPS7A4901DGN | HVSSOP-8 PowerPAD | 36 V-input adjustable LDO set to 5.0 V. Verify exact orderable suffix and thermal pad footprint. |
| U8 | 1 | TPS7A4901DGN | HVSSOP-8 PowerPAD | Second high-voltage LDO set to approximately 12.0 V for DAC AVDD. |
| U2 | 1 | TLV75533PDBVR | SOT-23-5 | Fixed 3.3 V LDO from the 5 V field rail. |
| U3 | 1 | ADuM4151ARIZ | 20-lead wide SOIC | 5 kV rms-rated SPI digital isolator, two forward and one reverse auxiliary channels. The component rating does not by itself certify the assembled product. |
| U4 | 1 | AD5754RBREZ | 24-lead TSSOP with exposed pad, RE-24 | Quad 16-bit voltage-output DAC with internal reference. Use channel A; power down B-D. |
| U5 | 1 | ADS8688IDBT | TSSOP-38, DBT | Eight-channel 16-bit ADC with 0-10.24 V input range; tube ordering code is convenient for prototypes. |
| U6, U7 | 2 | LTV-817S-TA1-C or equivalent high-CTR optocoupler | SOP-4 | Active-low `SETPOINT_OK_N` and `OUTPUT_ON_N` receivers. Confirm CTR at approximately 2 mA LED current; increase LED current within MDX limits if required. |
| K1-K3 | 3 | G3VM-61G1 | SOP-4 | Normally-open 60 V MOSFET relays for remote-on, P-regulation and I-regulation contacts. Maximum trigger current is 3 mA; the design uses about 5 mA nominal. |

### Connectors, protection, and test hardware

| References | Qty | Description | Rating / footprint | Notes |
|---|---:|---|---|---|
| J1 | 1 | 2x8 keyed board-to-board/backplane connector | Connector family selected with backplane mechanics | Carries controller-domain SPI, selects, reset, relay drives, status returns, 3.3 V and ground. It is not a Pico cable. |
| J2 | 1 | Male DB-25 connector with metal shell and screw locks | Through-hole right-angle or panel/cable type | Must mate with the MDX female User port. Select the exact mechanical part after enclosure and cable-entry decisions. |
| F1 | 1 | Fast-acting fuse | 63 mA, at least 32 V | **Provisional.** Choose cartridge/holder or SMD part after measuring startup current; do not treat it as a precise 100 mA limiter. |
| D1 | 1 footprint | Low-leakage transient suppressor | At least 18 V stand-off; footprint to suit selected part | **DNP.** Populate only after measuring the auxiliary rail and proving the clamp cannot overload pin 14 or introduce leakage/error. |
| TP1 | 1 | `+15V_F` test point | Loop or SMD pad | Field side. |
| TP2 | 1 | `+12V_A` test point | Loop or SMD pad | DAC analog rail. |
| TP3 | 1 | `+5V_F` test point | Loop or SMD pad | ADC analog rail. |
| TP4 | 1 | `+3V3_F` test point | Loop or SMD pad | Field digital rail. |
| TP5 | 1 | `GND_MDX` test point | Loop or SMD pad | Field reference only. |
| TP6 | 1 | `GND_CTL` test point | Loop or SMD pad | Controller reference only; must remain isolated from TP5. |
| TP7 | 1 | DAC output before R20 | Small SMD pad | Permits DAC testing with J2 disconnected. |
| TP8 | 1 | J2.23 filtered level output | Small SMD pad | Permits checking the complete setpoint path. |
| MH1-MH4 | 4 | Plated or non-plated mounting holes | M3, enclosure dependent | Keep copper clearance appropriate to the mounting hardware and isolation zones. |

### Resistors

Use at least 50 ppm/degree C thin-film resistors for regulator feedback and
analog paths. General digital pull resistors may be ordinary 1% thick-film.

| References | Qty | Value | Tolerance / rating | Package | Function |
|---|---:|---:|---|---|---|
| R1 | 1 | 324 kohm | 0.1%, 25 ppm/degree C | 0603 or 0805 | U1 upper feedback resistor; with R2 gives approximately 5.02 V using nominal 1.185 V feedback reference. Recalculate from the selected regulator revision. |
| R2 | 1 | 100 kohm | 0.1%, 25 ppm/degree C | 0603 or 0805 | U1 lower feedback resistor. |
| R3 | 1 | 910 kohm | 0.1%, 25 ppm/degree C | 0805 | U8 upper feedback resistor; with R4 gives approximately 11.97 V. Recalculate before release. |
| R4 | 1 | 100 kohm | 0.1%, 25 ppm/degree C | 0603 or 0805 | U8 lower feedback resistor. |
| R5, R6 | 2 | 0 ohm | 1% | 0603 | Configuration links for U1/U8 enable connections; replace with required enable networks if sequencing analysis demands it. |
| R10-R12 | 3 | 430 ohm | 1%, 0.1 W | 0603 | Backplane 74HC595-to-G3VM relay LED current limiting, approximately 5 mA nominal. |
| R13, R14 | 2 | 6.8 kohm | 1%, 0.125 W or greater | 0805 | MDX +15 V to status optocoupler LED current limiting, approximately 2 mA. |
| R15, R16 | 2 | 10 kohm | 1% | 0603 | Pico-side status-input pull-ups to `3V3_CTL`. |
| R17, R18 | 2 | 10 kohm | 1% | 0603 | Field-side ADC and DAC chip-select pull-ups. |
| R19 | 1 | 10 kohm | 1% | 0603 | Field-side `AFE_RESET_N` pull-down. |
| R20 | 1 | 100 ohm | 0.1%, 25 ppm/degree C | 0805 | DAC-output isolation/EMI resistor. |
| R21-R24 | 4 | 1.00 kohm | 0.1%, 25 ppm/degree C | 0805 | ADC monitor input filter/protection resistors. |
| R25, R26 | 2 | 0 ohm | 0.1 W | 0805 | Optional star-point links for separately routed analog/control returns; fit only as shown by the final grounding plan. |
| R30-R32 | 3 | 33 ohm | 1% | 0603 | Series damping on field-side SCLK, MOSI, and MISO. |

### Capacitors

Voltage ratings below are minimums. Use X7R unless C0G/NP0 is specified and
check effective capacitance at the applied DC bias. The ADS8688 reference
capacitors should be placed exactly as its data sheet specifies.

| References | Qty | Value | Dielectric / minimum rating | Package | Function |
|---|---:|---:|---|---|---|
| C1 | 1 | 10 uF | X7R, 25 V | 1210 | Bulk capacitor after F1 on `+15V_F`. |
| C2 | 1 | 100 nF | X7R, 50 V | 0603 | High-frequency bypass on `+15V_F`. |
| C3 | 1 | 2.2 uF | X7R, 25 V | 0805/1206 | U1 input bypass. |
| C4 | 1 | 10 uF | X7R, 10 V | 0805/1206 | U1 5 V output/stability capacitor. |
| C5 | 1 | 10 nF | C0G/NP0, 25 V | 0603 | U1 noise-reduction capacitor; confirm value and connection from the TPS7A49 data sheet. |
| C6 | 1 | 2.2 uF | X7R, 25 V | 0805/1206 | U8 input bypass. |
| C7 | 1 | 10 uF | X7R, 25 V | 1206 | U8 12 V output/stability capacitor. |
| C8 | 1 | 10 nF | C0G/NP0, 25 V | 0603 | U8 noise-reduction capacitor; confirm against data sheet. |
| C9 | 1 | 4.7 uF | X7R, 10 V | 0805 | U2 input bypass. |
| C10 | 1 | 4.7 uF | X7R, 6.3 V or greater | 0805 | U2 3.3 V output/stability capacitor. |
| C11, C13 | 2 | 100 nF | X7R, 10 V | 0603 | ADuM4151 VDD1 and VDD2 high-frequency bypass. |
| C12, C14 | 2 | 1 uF | X7R, 10 V | 0603/0805 | ADuM4151 local bulk bypass, one on each side. |
| C15, C17 | 2 | 100 nF | X7R, 25 V for C15; 10 V for C17 | 0603 | AD5754R AVDD and DVCC high-frequency bypass. |
| C16 | 1 | 10 uF | low-ESR X7R/tantalum, 25 V | 1206 or case A | AD5754R AVDD bulk bypass. |
| C18 | 1 | 10 uF | low-ESR X7R/tantalum, 10 V | 0805/1206 | AD5754R DVCC bulk bypass. |
| C20 | 1 | 10 nF | C0G/NP0, 25 V | 0805 | DAC output EMI filter to the pin-21 analog return. |
| C21, C22 | 2 | 1 uF | X7R, 10 V | 0603 | ADS8688 AVDD bypass, one directly at each AVDD pin. |
| C23 | 1 | 10 uF | X7R, 10 V | 0805 | ADS8688 AVDD bulk bypass. |
| C24 | 1 | 10 uF | X7R, 10 V | 0805 | ADS8688 DVDD bypass. |
| C25 | 1 | 10 uF | X7R, 10 V | 0805 | ADS8688 REFIO-to-REFGND decoupling for internal reference. |
| C26 | 1 | 1 uF | X7R, 10 V | 0603 | ADS8688 REFCAP high-frequency decoupling; no vias to pins. |
| C27 | 1 | 22 uF | X7R, 10 V | 1210 | ADS8688 REFCAP charge reservoir; no vias to pins. |
| C30-C33 | 4 | 100 nF | C0G/NP0 or film, 25 V | 1206 or suitable film footprint | ADC monitor RC filters. C0G at this value is relatively large/costly; retain a film-capacitor option. |

### Controller/backplane electronics: one set per eight-channel system

Reference designators in this table are reserved for the controller schematic
and do not collide with the per-channel-card references above.

| References | Qty | Part / value | Package | Function and notes |
|---|---:|---|---|---|
| P100 | 1 | Raspberry Pi Pico or Pico W | Castellated Pico module | Mount directly on the controller PCB. Keep USB accessible at the enclosure edge. |
| U100 | 1 | SN74LVC244APW | TSSOP-20 | Eight-channel backplane fan-out buffer: four SCLK and four MOSI outputs, each serving at most two slots. |
| U101, U102 | 2 | SN74HC138PW | TSSOP-16 | Active-low 3-to-8 decoders for ADC and DAC chip selects. Pull enables to their inactive state. |
| U103 | 1 | SN74HC151PW | TSSOP-16 | Eight-to-one MISO multiplexer selected by `SLOT_A[2:0]`. Do not join ADuM MI outputs directly. |
| U110-U112 | 3 | SN74HC595PW | TSSOP-16 | Twenty-four relay command bits with one shared latch and output enable. |
| U120, U121 | 2 | SN74HC165PW | TSSOP-16 | Sixteen parallel status inputs shifted to the Pico. |
| U130 | 1 | watchdog/supervisor, final part TBD | package TBD | Must require periodic Pico activity and remove `REMOTE_OUTPUT_PERMIT` on reset/hang. Select after timeout and polarity are fixed. |
| U131 | 1 | 3.3 V load switch or relay-LED permit stage, final part TBD | package TBD | Gates current to all `REMOTE_ON` MOSFET-relay LEDs; default off with a hardware pull-down. |
| RN100-RN102 | 3 | 8x 10 kohm resistor arrays | 0603 array or TSSOP network | Default-off/inactive pulls for relay outputs, status inputs, decoder enables and spare lines; allocate explicitly in schematic. |
| R100-R107 | 8 | 22-47 ohm | 0603 | Source-series termination, one per U100 SCLK/MOSI fan-out output; choose by measurement. |
| C100-C110 | 11 | 100 nF X7R | 0603 | One local decoupler per controller/backplane IC. Add one for the watchdog/load switch as required. |
| C111-C113 | 3 | 10 uF X7R | 0805 | Controller 3.3 V bulk decoupling at Pico, logic bank and slot connectors. |
| J100-J107 | 8 | mating channel-card connectors | matches J1 | One keyed slot connector per MDX channel. Unused slots must be electrically benign. |
| TP100-TP106 | 7 | logic test points | SMD pads | SCLK, MOSI, selected MISO, ADC enable, DAC enable, relay latch, and output permit. |

The watchdog and output-permit components remain deliberately unresolved: their
timeout, reset polarity, drive current, diagnostic feedback, and behaviour
during firmware update must be specified before choosing parts. No firmware
implementation can replace this hardware default-off path.

### PCB, cable, and enclosure items

| Item | Qty | Requirement |
|---|---:|---|
| Four-layer controller/backplane PCB | 1 | Carries the Pico, multiplexers, decoders, shift registers, watchdog, and up to eight card connectors. No Pico-to-SPI cable is required. |
| Four-layer channel-card PCB | 1 per MDX | Maintain separate controller and field ground/power planes with the ADuM keep-out respected. Use an isolation slot only if supported by the final mechanical and safety review. |
| Shielded DB-25 cable | 1 | Straight-through, individually screened or overall shielded cable suitable for the installation environment; keep analog returns paired with their signals. |
| Metal enclosure | 1 | Bond DB-25 shell and cable shield to enclosure at entry. Do not use the signal-ground plane as the shield-current path. |
| Labels | as required | Mark the MDX channel, 5 V/10 V analog configuration, board revision, connector orientation, and test-point domains. |

### Parts-list release gates

Before converting this table into a purchasing BOM:

1. Import manufacturer symbols and footprints and verify every pin number
   against the current data sheets.
2. Recalculate both TPS7A4901 feedback networks and complete their stability,
   startup-sequencing, and thermal calculations.
3. Measure the MDX pin-14 voltage range, startup behaviour, source impedance,
   and available current on the actual supply revision.
4. Select J2, F1, D1, mounting hardware, enclosure, and cable as a single
   mechanical/EMC design.
5. Run schematic ERC, isolation/creepage review, analog error-budget review,
   worst-case power budget, and an independent safety review.
6. Verify with an oscilloscope that decoder changes never generate a chip-select
   glitch, that only one MISO source reaches the Pico, and that relay-latch skew
   is comfortably below 100 ms across all populated slots.
7. Demonstrate that Pico reset, firmware lockup, USB disconnection, and
   controller-power loss all remove `REMOTE_OUTPUT_PERMIT` without software.
