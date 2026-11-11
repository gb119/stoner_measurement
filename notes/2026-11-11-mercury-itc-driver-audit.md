# Mercury iTC driver command audit

## Evidence and scope

Audit date: 11 November 2026. Primary evidence is the Oxford Instruments
[Mercury iTC Operator's Manual, Issue 05, February 2015](https://lmu.web.psi.ch/docu/manuals/bulk_manuals/OxfordInstruments/Mercury_iTC_manual_Issue_05.pdf),
sections 4.8 (pp. 52–53) and 8.3 (pp. 103–113). Manufacturer-authored manual text is
also available in the [manual mirror](https://www.manualslib.com/manual/1542196/Oxford-Instruments-Omicron-Nanoscience-Mercuryitc.html).
This audit concerns the temperature controller, not Mercury iPS magnet supplies or Heliox.

The previous driver sent fixed READ:TEMP?, READ:LOOPn and SET:NEEDLEVALVE commands.
Those are not the native Mercury iTC command tree. The replacement implements the
published device-addressed READ/SET grammar with newline framing and acknowledged SETs.

## Corrected native paths

| Area | Native path, following READ: or SET: | Evidence |
| --- | --- | --- |
| Discovery | SYS:CAT | 8.3.5.1 |
| Temperature | DEV:uid:TEMP:SIG:TEMP | 8.3.5.2 |
| Existing heater/auxiliary association | DEV:uid:TEMP:LOOP:HTR or AUX | 8.3.5.3 |
| Target temperature | DEV:uid:TEMP:LOOP:TSET | 4.8, 8.3.5.3 |
| Heater automatic control | DEV:uid:TEMP:LOOP:ENAB | 8.3.5.3 |
| Manual heater demand | DEV:uid:TEMP:LOOP:HSET | 8.3.5.3 |
| PID terms and table selection | DEV:uid:TEMP:LOOP:P, I, D and PIDT | 8.3.5.3 |
| Continuous ramp | DEV:uid:TEMP:LOOP:RSET and RENA | 4.8 |
| Manual flow and flow automatic mode | DEV:uid:TEMP:LOOP:FSET and FAUT | 8.3.5.3 |
| Measured heater power / available maximum | DEV:heater:HTR:SIG:POWR and PMAX | 8.3.5.4 |
| Actual valve position | DEV:aux:AUX:SIG:OPEN | Auxiliary signal reference |

## Framing, responses and capabilities

MercuryProtocol retains native STAT replies, parses inline rejection tokens and never
polls the unsupported SYST:ERR? queue. SET acknowledgements are consumed before the next
request and checked against the addressed path. Missing, mismatched, INVALID, NOT_FOUND,
N/A and DENIED replies raise errors without replaying a state-changing command. The
engine now selects MercuryProtocol instead of the ITC503 carriage-return protocol.
Native SI suffixes and optional VALID suffixes are parsed; incompatible units and
non-finite readings are rejected. The documented maximum native line length is 1024 bytes.

Capabilities come from SYS:CAT and existing LOOP:HTR/AUX associations, not assumed board
counts. Sensor aliases A onwards follow sorted temperature-board UIDs. Loop numbers follow
the sensors with assigned heaters. The exposed input selector for each loop is restricted
to its owning sensor. Changing hardware heater/sensor associations belongs to instrument
configuration followed by reconnect; discovery never creates or rewires a loop.
Disconnected and partially failed connections discard their catalogue references.

Manual heater/gas demand accepts 0–100 percent. Heater mode changes do not write FAUT;
flow-mode changes do not write ENAB. Off first disables automatic heater control and then
sets manual demand to zero. Like the ITC503, hardware reports this as manual/open loop,
not a distinct off mode. Actual heater output is derived from measured watts divided by
the hardware's reported maximum watts, rather than presenting cached HSET demand as measured
output. Actual valve position is read from the associated auxiliary signal.

Mercury has no discrete heater power ranges. The false Off/On range is removed from
capabilities and the UI. Native voltage/power limits are not changed incidentally.
Generic gas controls are exposed only for exactly one configured auxiliary association;
multiple valve loops are not resolved by selecting an arbitrary board.

Firmware 1.4.40 introduced continuous ramp support. RSET and RENA are advertised only
when the identified firmware supports them. Apply sets the ramp configuration before
writing the target, as the manual requires. It does not start an existing stored sweep.
FAUT uses Manual/Auto for Cryosys 1.0.11 and older and OFF/ON for newer firmware.
The minimum native ramp version does not imply that all old firmware has identical
command support; unsupported replies remain visible to callers.

Existing PID files can be selected with Zone mode, but file contents are not represented
by the generic zone-table editor. No table-editing capability is advertised. Native PID
terms retain the firmware's own units; the driver does not reinterpret I or D as SI seconds.
Finite-temperature status indicates signal availability, not a decoded hardware alarm log.
The driver does not advertise full alarm handling or engineering configuration.

## Verification and bench checks

The new test module replaces the old fictional-command Mercury core test with native
coverage of discovery, independent modes, SI parsing, acknowledgements, error propagation,
limits, firmware gating, ownership cleanup, multiple-board configurations and real primary
Apply clicks through the engine. The combined regression suite passed 478 tests on
Windows with offscreen PyQt5; this is not a claim of physical instrument validation.

Bench check the native identity, catalogue, sorted sensor aliases and heater/auxiliary
associations first. Compare temperature and target readback with the front panel. Apply a
small target change with a chosen ramp rate, then verify independent heater and gas modes,
manual demand, actual power/valve position, Off and repeated Apply/Read exchanges. Confirm
the selected remote interface and PID file on the instrument before operating it. Recheck
associations after reconnect or changes to installed boards.
