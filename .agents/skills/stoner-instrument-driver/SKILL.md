---
name: stoner-instrument-driver
description: Implement, extend or debug concrete stoner_measurement instrument drivers and their protocol or transport integration. Use for hardware command handling, capabilities, acquisition and driver lifecycle work; not plugin-only orchestration, UI-only changes or documentation-only plugin audits.
---

# Stoner instrument driver development

Deliver the requested instrument operations through the repository's existing
driver interfaces, backed by model-specific evidence and focused tests.

## Establish the instrument contract

Read [AGENTS.md](../../../AGENTS.md) and the applicable
[development rules](../../../.github/copilot-instructions.md). Resolve links
relative to this skill directory. Search `notes/` for the instrument's programming
guide or approved implementation brief before designing its API.

Inspect the instrument-family abstraction and a nearby concrete driver under
`src/stoner_measurement/instruments/`. Check the current `BaseInstrument`,
`protocol/`, `transport/`, error classes and capability conventions. Use existing
public methods and units; keep model-specific extensions behind explicit names.

For the operations being changed, establish:

- The exact model and relevant firmware or interface variant, supported
  quantities, units, ranges and discrete settings.
- The command grammar, response format, terminators or frame lengths, and any
  ordering, trigger, completion or status requirements.
- Which layer owns the connection and whether the resource is shared, including
  any controller or pass-through route.
- Which behaviour is required by the existing family interface and which is
  optional capability or model-specific functionality.

Use the manufacturer's manual and the repository brief as evidence. Fetch the
authoritative documentation when required details are missing; record useful
section or page references in developer notes. Do not infer commands or status
bits from a similarly named instrument. Resolve contradictions explicitly and
identify assumptions that still require bench validation. Scale this evidence
to the change rather than producing a new design document for every small fix.

## Implement at the appropriate layer

- Keep instrument-specific commands inside the instrument package. Drivers
  implement instrument operations, protocols format and parse messages, and
  transports carry bytes. Reuse the existing composition and injection paths;
  do not embed a second VISA or serial connection in a driver or plugin.
- Implement the requested operations fully through the family contract. Do not
  substitute a skeleton or advertise unimplemented capabilities. Preserve
  supported model choices and compatible defaults in affected integrations.
- Validate quantities and supported settings before sending commands. Follow
  established conversion and rounding semantics. Distinguish queried readback
  from cached requested values; do not report a cached value as measured state.
- Preserve framing, encoding, binary block lengths, byte order and response
  consumption. Use existing raw/binary helpers where appropriate. Legacy
  IEEE-488 commands need not support SCPI identification or error queries.
- Use the shared resource lock and transaction conventions. Where a multi-step
  command exchange must be atomic, hold the appropriate lock across the whole
  exchange, including pass-through routing and response retrieval.
- Match error checking to the protocol and model. Preserve meaningful timeout,
  malformed-response, instrument-status and unsupported-operation failures.
  Keep logging consistent with repository rules and existing communications
  logging rather than creating a parallel logging mechanism.
- Base reset, flush, retry and completion handling on documented behaviour.
  Keep waits bounded and honour cancellation where the surrounding API supports
  it. Do not replay a state-changing command blindly after an ambiguous timeout,
  or suppress errors globally to make startup appear successful.
- Respect resource ownership during failed startup, disconnect and reconnect.
  Inspect the actual driver and calling plugin lifecycle; do not assume the
  plugin reconnect wrapper also applies to drivers. Release owned partial
  resources and propagate cleanup failures without closing shared services.
- Preserve established output, trigger and cleanup semantics. Calibration,
  motion or output activation must not become incidental identification or
  connection behaviour unless the approved instrument contract requires it.

Update package exports, driver selectors, default configuration and dependent
consumers only where needed to make the requested driver usable. A driver task
does not automatically require creating a new sequence plugin.

## Verify and document

Read [testing guidance](../../../notes/testing_guidelines.md) before changing
tests and follow its migration-record requirements. Use the prescribed Conda
environment and existing fake transports or `NullTransport` for focused checks.

Test changed observable contracts: exact command/response exchanges, units and
range boundaries, relevant status decoding, malformed or partial responses,
timeout/recovery behaviour and owned-resource cleanup. Include automatic error
polling in scripted responses when enabled. Derive expected bytes from the
manual, not by copying the implementation's formatter into the test.

Run affected driver, protocol and integration tests as warranted by the change.
Check capability consumers when supported choices change. Do not execute
hardware-connected examples as routine documentation or test validation.

Document public behaviour, supported interfaces and limits using the repository
docstring conventions. Keep developer evidence in `notes/` and user-facing
Sphinx documentation in `docs/`. Report checks actually run, manual evidence and
remaining uncertainties. Fake-transport success does not establish physical
instrument behaviour; give a concise bench check for any unverified timing,
triggering, output or recovery behaviour relevant to the change.
