"""Driver for the legacy two-axis X-ray diffractometer controller."""

from __future__ import annotations

import time
from collections.abc import Callable

from stoner_measurement.instruments.xray.protocol import (
    FRAME_SIZE,
    LegacyXrayProtocol,
    XrayBcdError,
    XrayFrameLengthError,
    XrayOpcode,
    XraySnapshot,
    decode_snapshot,
)
from stoner_measurement.instruments.xray_diffractometer import (
    AxisDirection,
    CancelCheck,
    CountResult,
    DiffractometerMechanics,
    XrayDiffractometer,
    XrayOperationCancelled,
    XrayPositionError,
    cancellation_requested,
)


class LegacyXrayDiffractometer(XrayDiffractometer):
    """Control the two host-stepped axes and scalar counter over a byte stream."""

    DISPLAY_NAME = "Legacy X-ray Diffractometer"

    def __init__(
        self,
        transport,
        protocol: LegacyXrayProtocol | None = None,
        *,
        mechanics: DiffractometerMechanics | None = None,
        pre_read_delay_s: float = 0.010,
        retry_snapshot_once: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            transport=transport,
            protocol=protocol or LegacyXrayProtocol(),
            mechanics=mechanics or DiffractometerMechanics.recovered_site_defaults(),
        )
        self.pre_read_delay_s = max(0.0, float(pre_read_delay_s))
        self.retry_snapshot_once = bool(retry_snapshot_once)
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_snapshot: XraySnapshot | None = None

    def confirm_identity(self) -> str:
        """Confirm communication by decoding a snapshot (there is no ID query)."""
        self.read_snapshot()
        return self.DISPLAY_NAME

    def identify(self) -> str:
        return self.confirm_identity()

    def read_snapshot(self) -> XraySnapshot:
        """Read one atomic snapshot, with one flush-and-retry on framing failure."""
        attempts = 2 if self.retry_snapshot_once else 1
        last_error: Exception | None = None
        with self._lock:
            for attempt in range(attempts):
                try:
                    self.transport.write(bytes([XrayOpcode.READ_SNAPSHOT]))
                    if self.pre_read_delay_s:
                        self._sleep(self.pre_read_delay_s)
                    snapshot = decode_snapshot(self.transport.read(FRAME_SIZE))
                    self._validate_plausibility(snapshot)
                    self._last_snapshot = snapshot
                    return snapshot
                except (TimeoutError, XrayFrameLengthError, XrayBcdError) as exc:
                    last_error = exc
                    if attempt + 1 < attempts:
                        self.transport.flush()
            assert last_error is not None
            raise last_error

    def step_theta(
        self,
        direction: AxisDirection,
        steps: int = 1,
        *,
        interval_s: float = 0.010,
        cancel: CancelCheck = None,
    ) -> XraySnapshot:
        return self._step_axis("theta", direction, steps, interval_s, cancel)

    def step_two_theta(
        self,
        direction: AxisDirection,
        steps: int = 1,
        *,
        interval_s: float = 0.010,
        cancel: CancelCheck = None,
    ) -> XraySnapshot:
        return self._step_axis("two_theta", direction, steps, interval_s, cancel)

    def move_theta(
        self,
        angle_deg: float,
        speed_deg_per_min: float,
        *,
        cancel: CancelCheck = None,
        backlash: bool = True,
    ) -> XraySnapshot:
        return self._move_axis("theta", angle_deg, speed_deg_per_min, cancel, backlash)

    def move_two_theta(
        self,
        angle_deg: float,
        speed_deg_per_min: float,
        *,
        cancel: CancelCheck = None,
        backlash: bool = True,
    ) -> XraySnapshot:
        return self._move_axis("two_theta", angle_deg, speed_deg_per_min, cancel, backlash)

    def move_coupled(
        self,
        theta_deg: float,
        speed_deg_per_min: float,
        *,
        two_theta_offset_deg: float = 0.0,
        cancel: CancelCheck = None,
    ) -> XraySnapshot:
        """Move both axes to ``2theta = 2 * theta + offset`` with interleaved steps."""
        self._require_motion_enabled()
        two_theta_target = 2.0 * float(theta_deg) + float(two_theta_offset_deg)
        self._validate_target("theta", theta_deg)
        self._validate_target("two_theta", two_theta_target)
        if speed_deg_per_min <= 0.0:
            raise ValueError("speed_deg_per_min must be positive.")
        with self._lock:
            start = self.read_snapshot()
            theta_steps = self._target_steps("theta", start.theta_deg, theta_deg)
            two_theta_steps = self._target_steps(
                "two_theta", start.two_theta_deg, two_theta_target
            )
            interval = max(0.010, 60.0 / (400 * speed_deg_per_min))
            theta_backlash = (
                self.mechanics.theta.backlash_steps if theta_steps < 0 else 0
            )
            two_theta_backlash = (
                self.mechanics.two_theta.backlash_steps if two_theta_steps < 0 else 0
            )
            theta_excursion = (
                float(theta_deg)
                - theta_backlash / self.mechanics.theta.steps_per_degree
            )
            two_theta_excursion = (
                two_theta_target
                - two_theta_backlash / self.mechanics.two_theta.steps_per_degree
            )
            self._validate_target("theta", theta_excursion)
            self._validate_target("two_theta", two_theta_excursion)
            self._interleaved_steps(
                theta_steps - theta_backlash,
                two_theta_steps - two_theta_backlash,
                interval,
                cancel,
            )
            self._interleaved_steps(
                theta_backlash,
                two_theta_backlash,
                interval,
                cancel,
            )
            final = self.read_snapshot()
            self._verify_target("theta", theta_deg, final.theta_deg)
            self._verify_target("two_theta", two_theta_target, final.two_theta_deg)
            return final

    def start_count(self) -> None:
        self._write_opcode(XrayOpcode.START_COUNT)

    def stop_count(self) -> None:
        self._write_opcode(XrayOpcode.STOP_COUNT)

    def count(self, duration_s: float, *, cancel: CancelCheck = None) -> CountResult:
        """Perform a host-timed count and guarantee the stop opcode."""
        if duration_s < 0.0:
            raise ValueError("duration_s cannot be negative.")
        with self._lock:
            started = self._monotonic()
            self.transport.write(bytes([XrayOpcode.START_COUNT]))
            cancelled = False
            try:
                deadline = started + duration_s
                while self._monotonic() < deadline:
                    if cancellation_requested(cancel):
                        cancelled = True
                        break
                    self._sleep(min(0.050, max(0.0, deadline - self._monotonic())))
            finally:
                self.transport.write(bytes([XrayOpcode.STOP_COUNT]))
            elapsed = max(0.0, self._monotonic() - started)
            snapshot = self.read_snapshot()
            if cancelled:
                raise XrayOperationCancelled(
                    f"Count cancelled after {elapsed:.3f} s with {snapshot.counts} counts."
                )
            return CountResult(snapshot=snapshot, elapsed_s=elapsed)

    def zero_theta(self) -> None:
        self._write_opcode(XrayOpcode.ZERO_THETA)
        self._last_snapshot = None

    def zero_two_theta(self) -> None:
        self._write_opcode(XrayOpcode.ZERO_TWO_THETA)
        self._last_snapshot = None

    def reset_limit_latch(self) -> None:
        self._write_opcode(XrayOpcode.RESET_LIMIT_LATCH)

    def disable_theta(self) -> None:
        self._write_opcode(XrayOpcode.DISABLE_THETA)

    def disable_two_theta(self) -> None:
        self._write_opcode(XrayOpcode.DISABLE_TWO_THETA)

    def _move_axis(
        self,
        axis: str,
        target: float,
        speed: float,
        cancel: CancelCheck,
        backlash: bool,
    ) -> XraySnapshot:
        self._require_motion_enabled()
        self._validate_target(axis, target)
        if speed <= 0.0:
            raise ValueError("speed_deg_per_min must be positive.")
        mechanics = self._axis_mechanics(axis)
        interval = max(0.010, 60.0 / (mechanics.steps_per_degree * speed))
        with self._lock:
            start = self.read_snapshot()
            current = start.theta_deg if axis == "theta" else start.two_theta_deg
            signed_steps = self._target_steps(axis, current, target)
            if signed_steps < 0 and backlash and mechanics.backlash_steps:
                excursion = target - mechanics.backlash_steps / mechanics.steps_per_degree
                self._validate_target(axis, excursion)
                self._send_steps(
                    axis,
                    AxisDirection.NEGATIVE,
                    abs(signed_steps) + mechanics.backlash_steps,
                    interval,
                    cancel,
                )
                self._send_steps(
                    axis,
                    AxisDirection.POSITIVE,
                    mechanics.backlash_steps,
                    interval,
                    cancel,
                )
            else:
                direction = AxisDirection.POSITIVE if signed_steps >= 0 else AxisDirection.NEGATIVE
                self._send_steps(axis, direction, abs(signed_steps), interval, cancel)
            final = self.read_snapshot()
            actual = final.theta_deg if axis == "theta" else final.two_theta_deg
            self._verify_target(axis, target, actual)
            return final

    def _step_axis(
        self,
        axis: str,
        direction: AxisDirection,
        steps: int,
        interval_s: float,
        cancel: CancelCheck,
    ) -> XraySnapshot:
        self._require_motion_enabled()
        if steps < 0:
            raise ValueError("steps cannot be negative.")
        with self._lock:
            start = self.read_snapshot()
            mechanics = self._axis_mechanics(axis)
            current = start.theta_deg if axis == "theta" else start.two_theta_deg
            target = current + direction.value * steps / mechanics.steps_per_degree
            self._validate_target(axis, target)
            self._send_steps(axis, direction, steps, max(0.010, interval_s), cancel)
            return self.read_snapshot()

    def _interleaved_steps(
        self,
        theta_steps: int,
        two_theta_steps: int,
        interval: float,
        cancel: CancelCheck,
    ) -> None:
        total = max(abs(theta_steps), abs(two_theta_steps))
        if total == 0:
            return
        theta_done = two_done = 0
        for index in range(total):
            if cancellation_requested(cancel):
                raise XrayOperationCancelled("Coupled X-ray motion was cancelled.")
            theta_due = round((index + 1) * abs(theta_steps) / total)
            two_due = round((index + 1) * abs(two_theta_steps) / total)
            if theta_due > theta_done:
                self.transport.write(bytes([self._step_opcode("theta", _sign(theta_steps))]))
                theta_done += 1
            if two_due > two_done:
                self.transport.write(bytes([self._step_opcode("two_theta", _sign(two_theta_steps))]))
                two_done += 1
            self._sleep(interval)

    def _send_steps(
        self,
        axis: str,
        direction: AxisDirection,
        steps: int,
        interval: float,
        cancel: CancelCheck,
    ) -> None:
        opcode = self._step_opcode(axis, direction)
        for _ in range(steps):
            if cancellation_requested(cancel):
                raise XrayOperationCancelled(f"{axis} motion was cancelled.")
            self.transport.write(bytes([opcode]))
            self._sleep(interval)

    @staticmethod
    def _step_opcode(axis: str, direction: AxisDirection) -> XrayOpcode:
        if axis == "theta":
            return (
                XrayOpcode.STEP_THETA_CLOCKWISE
                if direction is AxisDirection.POSITIVE
                else XrayOpcode.STEP_THETA_ANTICLOCKWISE
            )
        return (
            XrayOpcode.STEP_TWO_THETA_CLOCKWISE
            if direction is AxisDirection.POSITIVE
            else XrayOpcode.STEP_TWO_THETA_ANTICLOCKWISE
        )

    def _write_opcode(self, opcode: XrayOpcode) -> None:
        with self._lock:
            self.transport.write(bytes([opcode]))

    def _target_steps(self, axis: str, current: float, target: float) -> int:
        mechanics = self._axis_mechanics(axis)
        return round((float(target) - current) * mechanics.steps_per_degree)

    def _validate_plausibility(self, snapshot: XraySnapshot) -> None:
        self._validate_target("theta", snapshot.theta_deg)
        self._validate_target("two_theta", snapshot.two_theta_deg)

    def _verify_target(self, axis: str, target: float, actual: float) -> None:
        tolerance = 1.1 / self._axis_mechanics(axis).steps_per_degree
        if abs(actual - float(target)) > tolerance:
            raise XrayPositionError(
                f"{axis} stopped at {actual:g} deg, expected {target:g} deg "
                f"within {tolerance:g} deg."
            )

def _sign(value: int) -> AxisDirection:
    return AxisDirection.POSITIVE if value >= 0 else AxisDirection.NEGATIVE
