# Legacy X-ray controller: analysis and Python-driver handoff

## Technical summary

The VB5 application controls a two-axis X-ray diffractometer and scalar counter through a custom ISA I/O card. The
application does **not** configure or use a Windows COM port, despite retaining an unused `MSCOMM32.OCX` project
reference. It writes one-byte commands to the card's data register at decimal port `785` (`0x311`), and the card's
UART/FIFO appears to serialize those bytes to the instrument. Reads are requested with byte `0xF0` and return a fixed
12-byte binary frame.

The supplementary `mod_SIO.bas`, from a different but related hardware setup, materially strengthens the FTDI migration
hypothesis. In that module the former `write(0x311, value)`-style path is replaced by
`WriteUSBDeviceBufferSIO(device_no, value, 1)`: the same numeric byte is passed with an explicit length of one, while
the old UART/FIFO/loopback reset routines become no-ops. It does not contain the USB helper declaration,
open/configuration code, or receive path, so it is corroborating evidence rather than a complete X-ray transport
specification.

The strongest working model for the FTDI replacement is therefore:

1. send the command byte exactly as a one-byte binary payload, with no ASCII conversion and no line terminator;
2. for `0xF0`, read exactly 12 bytes;
3. decode bytes 3-12 as packed decimal (BCD), least-significant digit first within the overall field;
4. treat bytes 1-2 as status, not numeric display data.

This is strongly supported by the source, but the USB/serial configuration layer is absent: the helper API
implementation, FTDI mode, baud rate, parity, stop bits, flow control, voltage levels, and whether any adapter firmware
adds/removes framing cannot be deduced from this repository. Those items require the missing USB support module/DLL,
FTDI configuration, an existing working program, hardware documentation, or a logic-analyser capture.

The supplied configuration files also recover the deployed mechanics profile: theta limits `-90..+90 deg`, 2-theta
limits `-30..+90 deg`, and backlash corrections of 100 theta steps and 50 2-theta steps. Both corrections equal `0.25
deg` at the recovered step scales. Treat these as installation defaults to confirm on the current mechanics, not as
universal protocol limits.

The owner has confirmed the coupled-motion geometry. Viewed from above, the
source is on the left, the sample/theta stage is central, and the detector is
on the right; the straight-through path is theta = 2-theta = 0 degrees. In an
increasing coupled reflection scan both the theta stage and the 2-theta
detector axis move clockwise, with the detector moving through twice the
sample angle.

## Documents

- [01_protocol_specification.md](01_protocol_specification.md) — byte-level command and response specification,
  including confidence labels.
- [02_legacy_software_behaviour.md](02_legacy_software_behaviour.md) — how motion, counting, scans, timing, backlash,
  and aborts work.
- [03_python_implementation_brief.md](03_python_implementation_brief.md) — implementation-ready architecture for
  `stoner_measurement`, tests, and acceptance criteria.
- [04_evidence_and_open_questions.md](04_evidence_and_open_questions.md) — traceable source evidence, code defects,
  uncertainties, and bench experiments.

## Most important safety constraints

Implementation status: [05_implementation_status.md](05_implementation_status.md).

- Do not test motion until command-byte transport has been verified with the motors disabled or mechanically safe.
- Never forward legacy writes to ports `0x310`, `0x312`, or `0x313` as instrument opcodes. They reset/configure the old
  PC interface card.
- Begin with the non-motion `0xF0` read request and verify a 12-byte reply.
- Preserve a single-owner lock around command/response activity. The protocol has no transaction identifier, checksum,
  or apparent resynchronisation marker.
- Do not zero either angular display (`0xB0`, `0xC0`) during exploratory testing; these commands mutate the
  instrument's position reference.

## Analysis scope and provenance

The analysis covers all VB source in this repository, with primary emphasis on `mod_IO_Communication.bas`, its older
copy `IO_Communication.bas`, `temp.frm`, `frm_ThetaControl.frm`, and `frm_ScanControler.frm`. This revision also
analyses `Xray_Setup.ini`, `Xray_system.ini`, and the related-system FTDI migration evidence in `mod_SIO.bas`. The
implementation guidance was checked against `stoner_measurement` commit `d90b3ba835dbac011ddc840cec1187b827715a00` (13
August 2026), particularly its binary-capable `SerialTransport`, protocol abstraction, and `MotorController` API. No
hardware was exercised.
