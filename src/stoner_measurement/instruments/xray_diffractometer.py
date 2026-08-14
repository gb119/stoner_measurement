"""Abstract instrument contract for two-axis X-ray diffractometers."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.xray.protocol import XraySnapshot


class XrayMotionError(InstrumentError):
    """Base class for rejected or unsuccessful diffractometer motion."""


class XrayMotionDisabledError(XrayMotionError):
    """Motion was requested before the mechanics profile was confirmed."""


class XrayTravelLimitError(XrayMotionError):
    """A requested target or backlash excursion exceeded a soft limit."""


class XrayPositionError(XrayMotionError):
    """The measured position did not agree with the requested motion."""


class XrayOperationCancelled(InstrumentError):
    """A cooperative move or count operation was cancelled."""


class AxisDirection(Enum):
    """Direction of increasing or decreasing angular coordinate.

    Viewed from above in reflection geometry, increasing theta is clockwise at
    the sample stage and increasing 2-theta is clockwise at the detector.
    Keeping this enum numerical still separates coordinate sign from opcode
    naming.
    """

    NEGATIVE = -1
    POSITIVE = 1


@dataclass(frozen=True)
class AxisMechanics:
    """Installation-specific mechanics for one host-stepped axis."""

    steps_per_degree: int
    minimum_deg: float
    maximum_deg: float
    backlash_steps: int = 0

    def validate(self) -> None:
        if self.steps_per_degree <= 0:
            raise ValueError("steps_per_degree must be positive.")
        if self.minimum_deg >= self.maximum_deg:
            raise ValueError("minimum_deg must be less than maximum_deg.")
        if self.backlash_steps < 0:
            raise ValueError("backlash_steps cannot be negative.")


@dataclass(frozen=True)
class DiffractometerMechanics:
    """Confirmed mechanics profile for both axes."""

    theta: AxisMechanics
    two_theta: AxisMechanics
    motion_enabled: bool = False

    def __post_init__(self) -> None:
        self.theta.validate()
        self.two_theta.validate()

    @classmethod
    def recovered_site_defaults(cls, *, motion_enabled: bool = False) -> DiffractometerMechanics:
        """Return the legacy installation values, requiring explicit enablement."""
        return cls(
            theta=AxisMechanics(400, -90.0, 90.0, 100),
            two_theta=AxisMechanics(200, -30.0, 90.0, 50),
            motion_enabled=motion_enabled,
        )


@dataclass(frozen=True)
class CountResult:
    """A completed count with its actual monotonic elapsed time."""

    snapshot: XraySnapshot
    elapsed_s: float

    @property
    def count_rate_hz(self) -> float:
        return self.snapshot.counts / self.elapsed_s if self.elapsed_s > 0.0 else 0.0


CancelCheck = threading.Event | Callable[[], bool] | None


class XrayDiffractometer(BaseInstrument, ABC):
    """Contract implemented by physical and simulated X-ray controllers."""

    def __init__(self, transport, protocol, *, mechanics: DiffractometerMechanics) -> None:
        super().__init__(transport=transport, protocol=protocol, auto_check_errors=False)
        self.mechanics = mechanics
        self._progress_callback: Callable[[XraySnapshot], None] | None = None

    def set_progress_callback(
        self, callback: Callable[[XraySnapshot], None] | None
    ) -> None:
        """Set an optional callback for intermediate motion snapshots."""
        self._progress_callback = callback

    def _publish_progress(self, snapshot: XraySnapshot) -> None:
        if self._progress_callback is not None:
            self._progress_callback(snapshot)

    @abstractmethod
    def read_snapshot(self) -> XraySnapshot:
        """Return one atomic theta, 2-theta and detector snapshot."""

    @abstractmethod
    def step_theta(
        self,
        direction: AxisDirection,
        steps: int = 1,
        *,
        interval_s: float = 0.010,
        cancel: CancelCheck = None,
    ) -> XraySnapshot:
        """Step the theta axis by an integer number of hardware steps."""

    @abstractmethod
    def step_two_theta(
        self,
        direction: AxisDirection,
        steps: int = 1,
        *,
        interval_s: float = 0.010,
        cancel: CancelCheck = None,
    ) -> XraySnapshot:
        """Step the 2-theta axis by an integer number of hardware steps."""

    @abstractmethod
    def move_theta(
        self,
        angle_deg: float,
        speed_deg_per_min: float,
        *,
        cancel: CancelCheck = None,
        backlash: bool = True,
    ) -> XraySnapshot:
        """Move theta to an absolute angular coordinate."""

    @abstractmethod
    def move_two_theta(
        self,
        angle_deg: float,
        speed_deg_per_min: float,
        *,
        cancel: CancelCheck = None,
        backlash: bool = True,
    ) -> XraySnapshot:
        """Move 2-theta to an absolute angular coordinate."""

    @abstractmethod
    def move_coupled(
        self,
        theta_deg: float,
        speed_deg_per_min: float,
        *,
        two_theta_offset_deg: float = 0.0,
        cancel: CancelCheck = None,
    ) -> XraySnapshot:
        """Move both axes while enforcing ``2theta = 2 * theta + offset``."""

    @abstractmethod
    def start_count(self) -> None:
        """Start the scalar detector counter."""

    @abstractmethod
    def stop_count(self) -> None:
        """Stop the scalar detector counter."""

    @abstractmethod
    def count(self, duration_s: float, *, cancel: CancelCheck = None) -> CountResult:
        """Acquire detector counts for a host-timed interval."""

    @abstractmethod
    def zero_theta(self) -> None:
        """Change the hardware theta datum to zero."""

    @abstractmethod
    def zero_two_theta(self) -> None:
        """Change the hardware 2-theta datum to zero."""

    @abstractmethod
    def reset_limit_latch(self) -> None:
        """Reset the controller's hardware limit latch."""

    @abstractmethod
    def disable_theta(self) -> None:
        """Send the controller's theta motor-disable operation."""

    @abstractmethod
    def disable_two_theta(self) -> None:
        """Send the controller's 2-theta motor-disable operation."""

    def _axis_mechanics(self, axis: str) -> AxisMechanics:
        return self.mechanics.theta if axis == "theta" else self.mechanics.two_theta

    def _validate_target(self, axis: str, target: float) -> None:
        mechanics = self._axis_mechanics(axis)
        if not mechanics.minimum_deg <= float(target) <= mechanics.maximum_deg:
            raise XrayTravelLimitError(
                f"{axis} target {target:g} deg is outside "
                f"[{mechanics.minimum_deg:g}, {mechanics.maximum_deg:g}] deg."
            )

    def _require_motion_enabled(self) -> None:
        if not self.mechanics.motion_enabled:
            raise XrayMotionDisabledError(
                "X-ray motion is disabled until the installation limits, "
                "directions and backlash profile are explicitly confirmed."
            )


def cancellation_requested(cancel: CancelCheck) -> bool:
    """Return whether a callable or event cancellation token is set."""
    if cancel is None:
        return False
    if isinstance(cancel, threading.Event):
        return cancel.is_set()
    return bool(cancel())
