"""Deterministic simulated X-ray diffractometer for UI and workflow testing."""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Sequence

from stoner_measurement.instruments.transport import NullTransport
from stoner_measurement.instruments.xray.protocol import (
    ControllerStatus,
    LegacyXrayProtocol,
    XraySnapshot,
)
from stoner_measurement.instruments.xray_diffractometer import (
    AxisDirection,
    CancelCheck,
    CountResult,
    DiffractometerMechanics,
    XrayDiffractometer,
    XrayOperationCancelled,
    cancellation_requested,
)

_DEFAULT_PEAKS = (
    (37.2, 12_000.0, 0.16),
    (43.4, 6_000.0, 0.20),
    (49.1, 15_000.0, 0.15),
    (54.0, 7_500.0, 0.22),
)

_CU_K_ALPHA_WAVELENGTH_NM = 0.15406
_COPPER_CRITICAL_ANGLE_DEG = 0.415


class SimulatedXrayDiffractometer(XrayDiffractometer):
    """Fast, reproducible simulation of motion, snapshots and scalar counts.

    Peak tuples are ``(two_theta_degrees, peak_rate_hz, sigma_degrees)``.
    Counting is instantaneous by default so tests need not wait in real time.
    """

    DISPLAY_NAME = "Simulated X-ray Diffractometer"

    def __init__(
        self,
        *,
        mechanics: DiffractometerMechanics | None = None,
        theta_deg: float = 0.0,
        two_theta_deg: float = 0.0,
        background_rate_hz: float = 40.0,
        peaks: Sequence[tuple[float, float, float]] = _DEFAULT_PEAKS,
        xrr_rate_hz: float = 100_000.0,
        xrr_wavelength_nm: float = _CU_K_ALPHA_WAVELENGTH_NM,
        xrr_critical_angle_deg: float = _COPPER_CRITICAL_ANGLE_DEG,
        xrr_film_thickness_nm: float = 50.0,
        xrr_fringe_amplitude: float = 0.35,
        xrr_roughness_nm: float = 0.5,
        xrr_phase_rad: float = 0.0,
        xrr_resolution_deg: float = 0.01,
        xrr_beam_height_mm: float = 0.05,
        xrr_sample_length_mm: float = 10.0,
        poisson_noise: bool = False,
        seed: int = 1,
        realtime: bool = False,
        motion_time_scale: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(
            transport=NullTransport(),
            protocol=LegacyXrayProtocol(),
            mechanics=mechanics
            or DiffractometerMechanics.recovered_site_defaults(motion_enabled=True),
        )
        self._sleep = sleep
        self._last_snapshot: XraySnapshot | None = None
        self._theta_deg = self._quantize("theta", theta_deg)
        self._two_theta_deg = self._quantize("two_theta", two_theta_deg)
        self._counts = 0
        self.background_rate_hz = max(0.0, float(background_rate_hz))
        self.peaks = tuple(peaks)
        self.xrr_rate_hz = max(0.0, float(xrr_rate_hz))
        self.xrr_wavelength_nm = _positive(
            "xrr_wavelength_nm", xrr_wavelength_nm
        )
        self.xrr_critical_angle_deg = max(0.0, float(xrr_critical_angle_deg))
        self.xrr_film_thickness_nm = max(0.0, float(xrr_film_thickness_nm))
        self.xrr_fringe_amplitude = min(1.0, max(0.0, float(xrr_fringe_amplitude)))
        self.xrr_roughness_nm = max(0.0, float(xrr_roughness_nm))
        self.xrr_phase_rad = float(xrr_phase_rad)
        self.xrr_resolution_deg = max(0.0, float(xrr_resolution_deg))
        self.xrr_beam_height_mm = max(0.0, float(xrr_beam_height_mm))
        self.xrr_sample_length_mm = _positive(
            "xrr_sample_length_mm", xrr_sample_length_mm
        )
        self.poisson_noise = bool(poisson_noise)
        self.realtime = bool(realtime)
        self.motion_time_scale = max(0.0, float(motion_time_scale))
        # This generator models measurement noise; it is not used for security or cryptography.
        self._random = random.Random(seed)  # nosec B311

    def confirm_identity(self) -> str:
        self.read_snapshot()
        return self.DISPLAY_NAME

    def identify(self) -> str:
        return self.confirm_identity()

    def read_snapshot(self) -> XraySnapshot:
        """Return the current simulated controller state."""
        with self._lock:
            frame = _encode_snapshot(self._theta_deg, self._two_theta_deg, self._counts)
            snapshot = XraySnapshot(
                theta_deg=self._theta_deg,
                two_theta_deg=self._two_theta_deg,
                counts=self._counts,
                status=ControllerStatus.from_bytes(0, 0x04),
                raw_frame=frame,
            )
            self._last_snapshot = snapshot
            return snapshot

    def step_theta(
        self,
        direction: AxisDirection,
        steps: int = 1,
        *,
        interval_s: float = 0.010,
        cancel: CancelCheck = None,
    ) -> XraySnapshot:
        return self._simulate_steps("theta", direction, steps, cancel)

    def step_two_theta(
        self,
        direction: AxisDirection,
        steps: int = 1,
        *,
        interval_s: float = 0.010,
        cancel: CancelCheck = None,
    ) -> XraySnapshot:
        return self._simulate_steps("two_theta", direction, steps, cancel)

    def move_theta(
        self,
        angle_deg: float,
        speed_deg_per_min: float,
        *,
        cancel: CancelCheck = None,
        backlash: bool = True,
    ) -> XraySnapshot:
        return self._simulate_move(
            "theta", angle_deg, speed_deg_per_min, cancel, backlash
        )

    def move_two_theta(
        self,
        angle_deg: float,
        speed_deg_per_min: float,
        *,
        cancel: CancelCheck = None,
        backlash: bool = True,
    ) -> XraySnapshot:
        return self._simulate_move(
            "two_theta", angle_deg, speed_deg_per_min, cancel, backlash
        )

    def move_coupled(
        self,
        theta_deg: float,
        speed_deg_per_min: float,
        *,
        two_theta_offset_deg: float = 0.0,
        cancel: CancelCheck = None,
    ) -> XraySnapshot:
        self._require_motion_enabled()
        if speed_deg_per_min <= 0.0:
            raise ValueError("speed_deg_per_min must be positive.")
        target_two_theta = 2.0 * theta_deg + two_theta_offset_deg
        self._validate_target("theta", theta_deg)
        self._validate_target("two_theta", target_two_theta)
        if cancellation_requested(cancel):
            raise XrayOperationCancelled("Simulated coupled motion was cancelled.")
        with self._lock:
            start_theta = self._theta_deg
            start_two_theta = self._two_theta_deg
            theta_backlash = (
                self.mechanics.theta.backlash_steps
                / self.mechanics.theta.steps_per_degree
                if theta_deg < start_theta
                else 0.0
            )
            two_theta_backlash = (
                self.mechanics.two_theta.backlash_steps
                / self.mechanics.two_theta.steps_per_degree
                if target_two_theta < start_two_theta
                else 0.0
            )
            excursion_theta = theta_deg - theta_backlash
            excursion_two_theta = target_two_theta - two_theta_backlash
            self._validate_target("theta", excursion_theta)
            self._validate_target("two_theta", excursion_two_theta)
            outbound_duration = max(
                abs(excursion_theta - start_theta) / speed_deg_per_min * 60.0,
                abs(excursion_two_theta - start_two_theta)
                / (2.0 * speed_deg_per_min)
                * 60.0,
            )
            outbound = self._animate_motion(
                start_theta,
                excursion_theta,
                start_two_theta,
                excursion_two_theta,
                outbound_duration,
                cancel,
            )
            correction_duration = max(
                theta_backlash / speed_deg_per_min * 60.0,
                two_theta_backlash / (2.0 * speed_deg_per_min) * 60.0,
            )
            if correction_duration == 0.0:
                return outbound
            return self._animate_motion(
                excursion_theta,
                theta_deg,
                excursion_two_theta,
                target_two_theta,
                correction_duration,
                cancel,
            )

    def count(self, duration_s: float, *, cancel: CancelCheck = None) -> CountResult:
        """Generate counts from the current 2-theta-dependent diffraction rate."""
        if duration_s < 0.0:
            raise ValueError("duration_s cannot be negative.")
        if self.realtime:
            deadline = time.monotonic() + duration_s
            while time.monotonic() < deadline:
                if cancellation_requested(cancel):
                    raise XrayOperationCancelled("Simulated count was cancelled.")
                self._sleep(min(0.050, max(0.0, deadline - time.monotonic())))
        elif cancellation_requested(cancel):
            raise XrayOperationCancelled("Simulated count was cancelled.")
        expected = self.detector_rate_hz(self._two_theta_deg) * duration_s
        self._counts = _poisson(self._random, expected) if self.poisson_noise else round(expected)
        return CountResult(snapshot=self.read_snapshot(), elapsed_s=float(duration_s))

    def start_count(self) -> None:
        self._counts = 0

    def stop_count(self) -> None:
        return None

    def detector_rate_hz(self, two_theta_deg: float | None = None) -> float:
        """Return the synthetic XRR and powder-diffraction count rate."""
        angle = self._two_theta_deg if two_theta_deg is None else float(two_theta_deg)
        rate = self.background_rate_hz + self.xrr_rate_hz * self.xrr_reflectivity(angle)
        for centre, amplitude, sigma in self.peaks:
            if sigma <= 0.0:
                continue
            rate += amplitude * math.exp(-0.5 * ((angle - centre) / sigma) ** 2)
        return rate

    def xrr_reflectivity(self, two_theta_deg: float | None = None) -> float:
        """Return a bounded thin-film XRR reflectivity for a specular scan.

        The ideal critical edge is broadened by the configured angular
        resolution and the whole curve is multiplied by the finite-sample
        beam-footprint factor. Above the edge, a Fresnel ``q_z**-4`` envelope
        is modulated by roughness-damped Kiessig fringes. ``two_theta_deg`` is
        converted to the incident angle using ``theta = two_theta / 2``.
        """
        two_theta = self._two_theta_deg if two_theta_deg is None else float(two_theta_deg)
        theta_deg = abs(two_theta) / 2.0
        q_z = _momentum_transfer(theta_deg, self.xrr_wavelength_nm)
        q_critical = _momentum_transfer(
            self.xrr_critical_angle_deg, self.xrr_wavelength_nm
        )
        postcritical = 1.0
        if q_z > 0.0 and q_critical > 0.0:
            fresnel = (q_critical / q_z) ** 4
            damping = math.exp(-((self.xrr_roughness_nm * q_z) ** 2))
            fringes = 1.0 + self.xrr_fringe_amplitude * damping * math.cos(
                q_z * self.xrr_film_thickness_nm + self.xrr_phase_rad
            )
            # Keep the Fresnel envelope as the upper bound while retaining the
            # requested fringe contrast within it.
            fringe_scale = fringes / (1.0 + self.xrr_fringe_amplitude)
            postcritical = min(1.0, max(0.0, fresnel * fringe_scale))

        edge = self.xrr_critical_edge_weight(two_theta)
        reflectivity = edge + (1.0 - edge) * postcritical
        return self.xrr_footprint_factor(two_theta) * reflectivity

    def xrr_critical_edge_weight(self, two_theta_deg: float | None = None) -> float:
        """Return the resolution-broadened total-reflection edge weight."""
        two_theta = self._two_theta_deg if two_theta_deg is None else float(two_theta_deg)
        theta_deg = abs(two_theta) / 2.0
        if self.xrr_resolution_deg == 0.0:
            return float(theta_deg <= self.xrr_critical_angle_deg)
        argument = (theta_deg - self.xrr_critical_angle_deg) / (
            math.sqrt(2.0) * self.xrr_resolution_deg
        )
        return 0.5 * math.erfc(argument)

    def xrr_footprint_factor(self, two_theta_deg: float | None = None) -> float:
        """Return the illuminated-sample fraction for the configured geometry."""
        two_theta = self._two_theta_deg if two_theta_deg is None else float(two_theta_deg)
        theta_deg = abs(two_theta) / 2.0
        ratio = min(1.0, self.xrr_beam_height_mm / self.xrr_sample_length_mm)
        footprint_angle_deg = math.degrees(math.asin(ratio))
        if footprint_angle_deg == 0.0:
            return 1.0
        return min(1.0, theta_deg / footprint_angle_deg)

    def zero_theta(self) -> None:
        self._theta_deg = 0.0

    def zero_two_theta(self) -> None:
        self._two_theta_deg = 0.0

    def reset_limit_latch(self) -> None:
        return None

    def disable_theta(self) -> None:
        return None

    def disable_two_theta(self) -> None:
        return None

    def _simulate_move(
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
        if cancellation_requested(cancel):
            raise XrayOperationCancelled(f"Simulated {axis} motion was cancelled.")
        with self._lock:
            start_theta = self._theta_deg
            start_two_theta = self._two_theta_deg
            current = start_theta if axis == "theta" else start_two_theta
            mechanics = self._axis_mechanics(axis)
            backlash_deg = (
                mechanics.backlash_steps / mechanics.steps_per_degree
                if backlash and target < current
                else 0.0
            )
            excursion = target - backlash_deg
            self._validate_target(axis, excursion)
            target_theta = excursion if axis == "theta" else start_theta
            target_two_theta = excursion if axis == "two_theta" else start_two_theta
            duration_s = abs(excursion - current) / speed * 60.0
            outbound = self._animate_motion(
                start_theta,
                target_theta,
                start_two_theta,
                target_two_theta,
                duration_s,
                cancel,
            )
            final_theta = target if axis == "theta" else start_theta
            final_two_theta = target if axis == "two_theta" else start_two_theta
            if backlash_deg == 0.0:
                return outbound
            return self._animate_motion(
                target_theta,
                final_theta,
                target_two_theta,
                final_two_theta,
                backlash_deg / speed * 60.0,
                cancel,
            )

    def _animate_motion(
        self,
        start_theta: float,
        target_theta: float,
        start_two_theta: float,
        target_two_theta: float,
        duration_s: float,
        cancel: CancelCheck,
    ) -> XraySnapshot:
        """Interpolate motion at a rate proportional to the requested speed."""
        scaled_duration = duration_s * self.motion_time_scale if self.realtime else 0.0
        frames = max(1, math.ceil(scaled_duration / 0.05))
        frame_delay = scaled_duration / frames
        for frame in range(1, frames + 1):
            if cancellation_requested(cancel):
                raise XrayOperationCancelled("Simulated X-ray motion was cancelled.")
            fraction = frame / frames
            self._theta_deg = self._quantize(
                "theta", start_theta + (target_theta - start_theta) * fraction
            )
            self._two_theta_deg = self._quantize(
                "two_theta",
                start_two_theta + (target_two_theta - start_two_theta) * fraction,
            )
            snapshot = self.read_snapshot()
            self._publish_progress(snapshot)
            if frame_delay:
                self._sleep(frame_delay)
        return self.read_snapshot()

    def _simulate_steps(
        self,
        axis: str,
        direction: AxisDirection,
        steps: int,
        cancel: CancelCheck,
    ) -> XraySnapshot:
        self._require_motion_enabled()
        if steps < 0:
            raise ValueError("steps cannot be negative.")
        if cancellation_requested(cancel):
            raise XrayOperationCancelled(f"Simulated {axis} motion was cancelled.")
        mechanics = self._axis_mechanics(axis)
        current = self._theta_deg if axis == "theta" else self._two_theta_deg
        target = current + direction.value * steps / mechanics.steps_per_degree
        self._validate_target(axis, target)
        return self._simulate_move(axis, target, 1.0, cancel, False)

    def _quantize(self, axis: str, angle: float) -> float:
        steps_per_degree = self._axis_mechanics(axis).steps_per_degree
        return round(float(angle) * steps_per_degree) / steps_per_degree


def _encode_snapshot(theta_deg: float, two_theta_deg: float, counts: int) -> bytes:
    return bytes((0, 0x04)) + _encode_le_bcd(counts, 4) + _encode_position(
        two_theta_deg, 200
    ) + _encode_position(theta_deg, 400)


def _momentum_transfer(theta_deg: float, wavelength_nm: float) -> float:
    """Return specular momentum transfer in inverse nanometres."""
    return 4.0 * math.pi * math.sin(math.radians(theta_deg)) / wavelength_nm


def _positive(name: str, value: float) -> float:
    """Return a positive float or reject an invalid physical parameter."""
    result = float(value)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive.")
    return result


def _encode_position(angle_deg: float, steps_per_degree: int) -> bytes:
    raw = round(angle_deg * steps_per_degree) % 1_000_000
    return _encode_le_bcd(raw, 3)


def _encode_le_bcd(value: int, width: int) -> bytes:
    if value < 0 or value >= 100 ** width:
        raise ValueError(f"Value {value} does not fit in {width} packed-BCD byte(s).")
    result = bytearray()
    remaining = int(value)
    for _ in range(width):
        pair = remaining % 100
        result.append((pair // 10) << 4 | pair % 10)
        remaining //= 100
    return bytes(result)


def _poisson(generator: random.Random, expected: float) -> int:
    """Draw a Poisson-like count without adding a NumPy dependency."""
    if expected <= 0.0:
        return 0
    if expected > 50.0:
        return max(0, round(generator.gauss(expected, math.sqrt(expected))))
    threshold = math.exp(-expected)
    product = 1.0
    count = 0
    while product > threshold:
        count += 1
        product *= generator.random()
    return count - 1
