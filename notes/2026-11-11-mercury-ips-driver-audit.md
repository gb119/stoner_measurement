# Mercury iPS connection and native-command audit

Evidence: Oxford Mercury iPS Operator's Manual, Issue 14, March 2016,
[chapter 10](https://www.manualslib.com/manual/2237399/Oxford-Instruments-Nanoscience-Mercuryips.html?page=116).
Printed pages 108–110 document newline framing, native colon-separated identity,
READ/SET replies, rejection tokens and SI scales. Pages 113–114 distinguish
individual supplies from axis groups and list their signals. Section 9.5 gives
front-panel local/remote selection. The earlier comparison in
`manget_power_supplies.md` is not an authoritative Mercury programming reference.

The magnet engine previously selected the legacy Oxford carriage-return
protocol for OxfordMercuryIPS. Direct driver construction instead selected a
generic SCPI protocol which polls the unsupported SYST:ERR? queue. Both now use
MercuryIPSProtocol: newline framing, native inline errors, direct response reads
without assumed IEEE-488.2 MAV/error bits. The iTC protocol is unchanged.

SET replies are now consumed and checked against the commanded path and value.
Rejected or mismatched acknowledgements stop a ramp sequence before ACTN; no
action is replayed. Native colon-separated model/firmware fields are parsed,
while existing comma-separated identities remain accepted. Connection failure
closes the transport without sending magnet commands.

The default is GRPZ, the conventional single-axis group. PSU.M1 names an
individual supply: ACTN, STAT and SWHT belong to a group. Other axes must use
their configured group UID through the driver constructor; automatic group
discovery and a vector-axis selector are outside this change. The driver does
not reconfigure hardware group membership, magnet calibration or remote access.

Field ramp rates use RFST, not the nonexistent RSET. Alarms use group STAT
hexadecimal flags, not SIG:STAF text. Nonzero flags report a general FAULT;
the manual does not give a supported quench-bit mapping. Numeric readbacks
validate units and apply documented SI prefixes instead of discarding them.
Multi-command ramps and status snapshots hold the shared instrument lock.

Disconnect no longer sends the undocumented PSU:CLOC command. Local/remote
selection remains on the front panel; disconnect does not ramp, change the
switch heater or disable the selected remote interface.

Connection failures now show a warning with the selected driver, transport,
address and exception reason. The main connection and polling log messages
also include exception details, retaining the traceback.

Verification: 217 tests passed on Python 3.14.10 / offscreen PyQt5 through
Miniforge Conda, covering engine-to-GPIB connection, native identity, failed
identity cleanup, acknowledgements, rejected ramps, SI units, alarm flags,
visible UI errors, magnet consumers, GPIB and adjacent iTC behaviour.
Ruff is unavailable in this environment; `git diff --check` passed.

Bench confirmation remains: restart and reconnect the single-axis iPS; compare
read-only field/current/voltage, RFST, STAT and heater readback with its front
panel. Verify the configured group is GRPZ. Only then test an operator-chosen
small target/rate and Hold under the laboratory's normal operating procedure.
No hardware commands were executed during this audit.
