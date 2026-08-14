# Evidence and open questions

## Evidence map

| Finding | Source |
|---|---|
| 8-bit card, decimal nibbles, 12-byte layout | introduction to `mod_IO_Communication.bas` |
| Ports 784-787 and complete opcodes | reset/command functions and `ReadData` in that module |
| Status bytes 1-2 | earlier `ReadData` in `temp.frm` |
| BCD ordering, scaling, signed wrap | both communication modules and `temp.frm` |
| Steps and motion timing | rotation functions in `frm_ThetaControl.frm` |
| Start/wait/stop/read count | `Xray_Count` in that form |
| Point scans | scan functions in `frm_ScanControler.frm` |
| No COM API use | repository search; `xray.vbp` only retains an unused MSCOMM reference |
| Deployed limits/backlash | `Xray_Setup.ini`, loaded by `mod_Setup.bas` and used by motion/scan forms |
| System/runtime INI roles | `Xray_system.ini`, `mod_Setup.bas`, `frm_ScanControler.frm`, and `frm_softwarecontrol.frm` |
| Related FTDI migration pattern | `mod_SIO.bas`: former data writes become `WriteUSBDeviceBufferSIO(device_no, value, 1)`; old card resets become no-ops |

High confidence: literal opcodes, fixed 12-byte response, BCD fields/scales, signed representation, host-generated steps, host-timed counts, and no visible terminator/checksum.

High confidence for a related installation: the intended migration maps each former data-register value to one USB write of length one and does not forward old UART/FIFO/loopback control writes.

Medium confidence for this X-ray installation: port-785 bytes pass unchanged through its FTDI path; motor low-nibble bit meanings; speed units; archaeological status abbreviations.

Owner-confirmed coupled geometry: viewed from above, the source is on the
left, the sample/theta stage is central, and the detector is on the right. The
straight-through path defines both angles as zero. In reflection geometry,
increasing coupled motion turns theta and the 2-theta detector axis clockwise;
the detector moves through twice the sample angle.

Unknown: USB helper implementation and receive API, FTDI mode, serial settings/electrical levels, converter firmware role, echo/latency, counter clearing/overflow, exact status meanings/axis mapping, hardware-limit and disable safety, reads during motion/counting, and additional opcodes.

## Highest-value experiments

1. Recover the module/DLL that declares `WriteUSBDeviceBufferSIO` and its open/read/configuration functions.
2. Inspect FTDI VID/PID, EEPROM, PCB, wiring, and existing configuration.
3. Logic-analyse a known `0xF0` transaction to determine baud/framing and transparent payload mapping.
4. Repeat 100+ rest snapshots; require length 12, valid BCD, and stable positions.
5. Change one safe hardware state and diff bytes 1-2.
6. Count known pulses/times to establish clear/latch/overflow semantics.
7. Single-step each motor opcode and verify axis/sign/resolution.
8. Exercise limit/disable behaviour only in a mechanically safe setup.

## Questions for the owner

1. Can the source module, type library, or DLL that provides `WriteUSBDeviceBufferSIO` (plus its device-open, read, and configuration calls) be recovered?
2. What FTDI part/board and mode (VCP, D2XX, bit-bang, custom wrapper/firmware) are installed on the X-ray system?
3. Is there an existing working FTDI X-ray application, configuration file, or recorded COM/native-driver setup?
4. Are signal levels TTL, RS-232 or RS-422/485, and is there isolation?
5. Are the supplied limits (theta `-90..90 deg`, 2-theta `-30..90 deg`) and `0.25 deg` backlash values still valid for the current mechanics?
6. Can motors and X-rays be independently inhibited for tests?
7. Does count-start clear the counter?
8. Can front-panel limit/overflow indicators be correlated with status bytes?

## Version caveat

The source snapshot has no accessible Git worktree metadata. CVS headers mention December 2007 and UI text mentions January 2007, but neither identifies the complete revision. Preserve this snapshot alongside future capture fixtures.
