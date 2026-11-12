# GPIB secondary-address parsing

`GpibTransport.from_resource_string` previously required exactly
`GPIB<board>::<primary>::INSTR`, rejecting the observed Mercury resource
`GPIB0::25::1::INSTR`. The separate BaseTransport VISA parser accepted this
string but discarded the secondary component, selecting a different endpoint.

Both now use the same parser for `GPIB[board]::primary[::secondary][::INSTR]`.
Omitted board means zero. Primary and secondary addresses are 0–30; omitted
secondary means none, distinct from secondary zero. Resource strings are
canonicalised with an explicit board and INSTR suffix. Secondary addressing
is retained in VISA open calls and resource keys, including the Keithley
pass-through subclass. Interface-only INTFC resources remain unsupported by
this instrument transport.

The syntax follows the manufacturer's VISA reference:
[Keysight: Addressing a Session](https://helpfiles.keysight.com/IO_Libraries_Suite/English/IOLS_Linux/VISA/Content/UsersGuide/chapter3/Addressing%20a%20Session.htm).
The extra component is a secondary GPIB address, rather than an instance index.

The observed identity has the existing supported structure:
`IDN:OXFORD INSTRUMENTS:MERCURY IPS:<serial>:<firmware>`.
The firmware example `2.2.6.20` is returned intact; the driver imposes no exact
version or component-count requirement. Production Mercury identity parsing
needed no change. Tests cover multiple firmware values and an engine-level
connection using the observed response format and resource address.

Validation: 187 transport, Mercury and instrument-locking tests passed through
the project Conda environment with offscreen PyQt5. Hardware remains untested;
reconnect the physical Mercury at its discovered resource and confirm identity
and passive field readback. No magnet output actions are needed for this check.
