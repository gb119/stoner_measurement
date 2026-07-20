# Common Instrument API for MKS PR4000B-S and PSR1A/PSR4A Controllers

<!-- markdownlint-disable MD013 -->

This note defines a common software API for two different MKS controller families:

- `PR4000B-S`
- `PSR1A` / `PSR4A`

The goal is not to pretend the two devices share a wire protocol. They do not. The goal is to define a shared application-level interface that lets higher-level code perform common tasks without caring which controller family is underneath.

---

## 1. Shared capabilities

Both controller families support a meaningful overlap in user-facing functionality:

- read an actual measured value
- read a configured setpoint
- write a setpoint
- read or configure engineering units
- read or configure full scale / range
- access controller configuration that affects scaling
- support mass-flow and pressure-control use cases
- communicate over RS232

Both also act as controller/readout devices rather than bare sensors.

---

## 2. Important differences that the common API must respect

### 2.1 Wire protocol

- `PR4000B-S`: single-character command protocol, `CR` terminated
- `PSR`: `AZ...` framed protocol with ports, indexed parameters, and structured replies

### 2.2 Serial framing

- `PR4000B-S`: `7` data bits, parity-configurable, `1` stop bit
- `PSR`: `9600 8N1`

### 2.3 Channel model

- `PR4000B-S`: effectively a single controller channel
- `PSR1A`: single channel
- `PSR4A`: multi-channel

### 2.4 Native features

- `PR4000B-S`: strong status-byte model, direct controller functions such as signal processing, autozero, and limits
- `PSR`: parameter-store model, explicit PV/SP configuration, batch and blend features, optional networking address

The common API should therefore abstract shared behaviors and expose device-specific features separately.

---

## 3. Common API design principles

Use:

1. a transport/protocol layer per family
2. a common abstract base class or protocol
3. optional capability mixins or feature flags for family-specific functions

A higher-level application should be able to ask:

- "What is the current value?"
- "What is the setpoint?"
- "Set the setpoint to X"
- "What units am I using?"
- "What is the configured full scale?"

without caring whether the backend is PR4000 or PSR.

---

## 4. Recommended common interface

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Optional, Protocol


class ControllerKind(str, Enum):
    PR4000B = "pr4000b"
    PSR = "psr"


class SignalDomain(str, Enum):
    FLOW = "flow"
    PRESSURE = "pressure"
    GENERIC = "generic"


@dataclass(frozen=True)
class EngineeringUnit:
    code: int | str
    name: str


@dataclass(frozen=True)
class Measurement:
    value: float
    unit: Optional[EngineeringUnit]
    channel: int = 1


@dataclass(frozen=True)
class ControllerRange:
    full_scale: float
    unit: Optional[EngineeringUnit]
    channel: int = 1


class CommonMKSController(Protocol):
    kind: ControllerKind

    def open(self) -> None: ...
    def close(self) -> None: ...

    def read_actual_value(self, channel: int = 1) -> Measurement: ...
    def read_setpoint(self, channel: int = 1) -> Measurement: ...
    def set_setpoint(self, value: float, channel: int = 1) -> None: ...

    def read_unit(self, channel: int = 1) -> Optional[EngineeringUnit]: ...
    def set_unit(self, unit_code: int | str, channel: int = 1) -> None: ...

    def read_range(self, channel: int = 1) -> ControllerRange: ...
    def set_range(self, full_scale: float, channel: int = 1) -> None: ...

    def identify(self) -> str: ...
```

This is the shared core.

---

## 5. Common operations that map well across both families

### 5.1 `read_actual_value(channel=1)`

Shared meaning:

- return the current measured process value

Backend mapping:

- `PR4000B-S`: use measured-value update command, not the setpoint read command
- `PSR`: use measured-channel values response or verified PV parameter readback

### 5.2 `read_setpoint(channel=1)`

Shared meaning:

- return the currently configured controller target

Backend mapping:

- `PR4000B-S`: direct setpoint read command
- `PSR`: SP-side parameter read for the SP Rate index, once the exact read syntax is hardware-verified

### 5.3 `set_setpoint(value, channel=1)`

Shared meaning:

- set the target for closed-loop control

Backend mapping:

- `PR4000B-S`: setpoint write command
- `PSR`: write SP Rate parameter on the output port for the requested channel

### 5.4 `read_unit(channel=1)` / `set_unit(...)`

Shared meaning:

- get or set engineering units used by the controller display/control scaling

Backend mapping:

- `PR4000B-S`: direct measurement-unit command
- `PSR`: PV-side units parameter and possibly matching SP-side scaling expectations

### 5.5 `read_range(channel=1)` / `set_range(...)`

Shared meaning:

- get or configure the effective full scale or range used for control/readback

Backend mapping:

- `PR4000B-S`: direct range command
- `PSR`: PV full scale and SP full scale, usually set together

For the PSR family, `set_range()` should update both PV and SP full scale together unless the caller explicitly wants them split.

---

## 6. Shared configuration model

A useful cross-family configuration object:

```python
@dataclass
class CommonChannelConfig:
    channel: int = 1
    domain: SignalDomain = SignalDomain.GENERIC
    unit: Optional[EngineeringUnit] = None
    full_scale: Optional[float] = None
    setpoint: Optional[float] = None
```

This should be populated from family-specific data:

- PR4000B-S direct reads
- PSR port/index reads

---

## 7. Family-specific extensions

Do not force these into the common base interface.

### 7.1 PR4000B-S-only features

- status byte reads and decoded status flags
- gain and offset commands
- limit mode and limit memory
- timeout
- signal processing mode
- display mode
- autozero
- autofullscale / autolinearization

Recommended extension interface:

```python
class PR4000Extended(Protocol):
    def read_status_bytes(self) -> tuple[int, int, int, int]: ...
    def autozero(self) -> None: ...
    def read_gain(self) -> float: ...
    def set_gain(self, value: float) -> None: ...
```

### 7.2 PSR-only features

- batch mode
- blend mode
- per-port parameter access
- network addressing
- PV signal type / SP signal type
- time base
- decimal placement
- gas correction factor

Recommended extension interface:

```python
class PSRExtended(Protocol):
    def set_parameter(self, port: str, index: int, value: str) -> None: ...
    def get_parameter(self, port: str, index: int) -> str: ...
    def configure_batch(self, channel: int, rate: float, quantity: float) -> None: ...
    def configure_blend(self, master: int, slave: int, ratio_percent: float) -> None: ...
```

---

## 8. Channel semantics

The common interface should always accept a `channel` argument, even for single-channel instruments.

Rules:

- default `channel=1`
- `PR4000B-S` should reject any channel other than `1`
- `PSR1A` should reject any channel other than `1`
- `PSR4A` should support channels `1` to `4`

This keeps higher-level code uniform.

---

## 9. Identification and capability discovery

The common API should expose both identity and capabilities.

Suggested capability model:

```python
@dataclass(frozen=True)
class ControllerCapabilities:
    channels: int
    supports_pressure: bool
    supports_flow: bool
    supports_status_bytes: bool
    supports_batch: bool
    supports_blend: bool
    supports_network_addressing: bool
```

Expected capabilities:

- `PR4000B-S`: `channels=1`, status bytes yes, batch no, blend no, networking no
- `PSR1A`: `channels=1`, status bytes no documented equivalent, batch yes, blend no, networking optional address model
- `PSR4A`: `channels=4`, batch yes, blend yes, networking optional address model

---

## 10. Error handling

Use shared top-level exceptions with family-specific subclasses.

```python
class MKSControllerError(Exception):
    pass


class MKSProtocolError(MKSControllerError):
    pass


class MKSConfigurationError(MKSControllerError):
    pass


class MKSUnsupportedFeatureError(MKSControllerError):
    pass
```

Family-specific examples:

- PR4000 status-byte error conditions can raise `MKSConfigurationError` or a PR4000-specific subclass
- PSR checksum or malformed structured reply should raise `MKSProtocolError`
- attempting blend on PR4000 or PSR1A should raise `MKSUnsupportedFeatureError`

---

## 11. Recommended implementation structure

Suggested package layout:

```text
mks/
  base.py
  units.py
  exceptions.py
  pr4000b.py
  psr.py
```

Suggested class structure:

```python
class BaseMKSController:
    kind: ControllerKind
    capabilities: ControllerCapabilities

    def open(self) -> None: ...
    def close(self) -> None: ...


class PR4000BController(BaseMKSController):
    ...


class PSRController(BaseMKSController):
    ...
```

This keeps:

- a shared public shape
- completely separate protocol implementations

That separation is important.

---

## 12. Normalizing units and scaling

One of the hardest cross-family issues is scaling.

### 12.1 PR4000B-S

- uses direct command values and device-defined numeric ASCII formats
- reports unit code separately

### 12.2 PSR

- uses indexed parameters
- uses decimal-placement and time-base settings
- can represent values as scaled fixed-point transport integers

The common API should therefore normalize values into engineering units at the boundary of the family-specific driver, not in the calling application.

In other words:

- the `PR4000B-S` backend should return `Measurement(value=..., unit=...)`
- the `PSR` backend should also return `Measurement(value=..., unit=...)`

even though the raw protocols are very different.

---

## 13. Common workflow examples

### 13.1 Read the current process value

```python
reading = controller.read_actual_value(channel=1)
print(reading.value, reading.unit.name if reading.unit else "")
```

### 13.2 Set a new target

```python
controller.set_setpoint(25.0, channel=1)
```

### 13.3 Configure a full scale

```python
controller.set_range(100.0, channel=1)
```

For PSR this should usually imply both PV full scale and SP full scale.

---

## 14. What not to unify too aggressively

Do not hide these differences behind one fake low-level command language:

- PR4000B-S status bytes
- PSR batch/blend
- PR4000B-S valve on/off command semantics
- PSR SP VOR semantics
- PR4000B-S signal processing controls
- PSR per-port signal type and decimal/time-base configuration

Those should remain explicit family-specific operations.

---

## 15. Recommended documentation strategy

For future driver work, keep three layers of notes:

1. controller-specific protocol guide for PR4000B-S
2. controller-specific protocol guide for PSR1A/PSR4A
3. this shared API note for application-facing design

This lets an LLM coding agent:

- understand the protocol details correctly
- still target one stable higher-level software interface

---

## 16. Source note

This shared API design is based on:

- [notes/PR4000B-S_driver_guide.md](/C:/stoner_measurement/notes/PR4000B-S_driver_guide.md)
- [notes/PSR1A-PSR4A_driver_guide.md](/C:/stoner_measurement/notes/PSR1A-PSR4A_driver_guide.md)
- [notes/source_manuals/PR4000B-S-man.pdf](/C:/stoner_measurement/notes/source_manuals/PR4000B-S-man.pdf)
- [notes/source_manuals/PSR1A-PSR4A-20068380-MAN.pdf](/C:/stoner_measurement/notes/source_manuals/PSR1A-PSR4A-20068380-MAN.pdf)
