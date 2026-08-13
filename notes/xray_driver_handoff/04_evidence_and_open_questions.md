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

High confidence: literal opcodes, fixed 12-byte response, BCD fields/scales, signed representation, host-generated steps, host-timed counts, and no visible terminator/checksum.

Medium confidence: port-785 bytes pass unchanged through FTDI; motor low-nibble bit meanings; speed units; physical direction labels; archaeological status abbreviations.

Unknown: serial settings/electrical levels, converter firmware role, echo/latency, counter clearing/overflow, exact status meanings/axis mapping, hardware-limit and disable safety, reads during motion/counting, and additional opcodes.

## Highest-value experiments

1. Inspect FTDI VID/PID, EEPROM, PCB, wiring, and existing configuration.
2. Logic-analyse a known `0xF0` transaction to determine baud/framing and transparent payload mapping.
3. Repeat 100+ rest snapshots; require length 12, valid BCD, and stable positions.
4. Change one safe hardware state and diff bytes 1-2.
5. Count known pulses/times to establish clear/latch/overflow semantics.
6. Single-step each motor opcode and verify axis/sign/resolution.
7. Exercise limit/disable behaviour only in a mechanically safe setup.

## Questions for the owner

1. What FTDI part/board and mode (VCP, D2XX, bit-bang, custom firmware) are installed?
2. Is there an existing working FTDI application or recorded COM configuration?
3. Are signal levels TTL, RS-232 or RS-422/485, and is there isolation?
4. Can motors and X-rays be independently inhibited for tests?
5. From what viewpoint are clockwise and anticlockwise defined?
6. Does count-start clear the counter?
7. Can front-panel limit/overflow indicators be correlated with status bytes?

## Version caveat

The source snapshot has no accessible Git worktree metadata. CVS headers mention December 2007 and UI text mentions January 2007, but neither identifies the complete revision. Preserve this snapshot alongside future capture fixtures.

