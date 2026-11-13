"""Read saved NI-DAQmx temperature tables without opening acquisition tasks."""

from collections.abc import Mapping

import numpy as np


def normalise_temperature_scale(scale: Mapping) -> dict:
    """Validate and copy a reversible kelvin-to-kelvin table snapshot.

    Args:
        scale (Mapping): Scale name and paired pre-scaled/scaled value arrays.

    Returns:
        (dict): YAML-compatible snapshot sorted by pre-scaled temperature.

    Raises:
        ValueError: If the table is not finite, non-negative and strictly monotonic.
    """
    x = np.asarray(scale.get("pre_scaled_values", []), dtype=float)
    y = np.asarray(scale.get("scaled_values", []), dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.size != y.size or x.size < 2:
        raise ValueError("A temperature scale requires at least two paired table values.")
    if not np.isfinite(x).all() or not np.isfinite(y).all() or (x < 0).any() or (y < 0).any():
        raise ValueError(
            "Temperature scale values must be finite, non-negative kelvin temperatures."
        )
    order = np.argsort(x)
    x, y = x[order], y[order]
    if not (np.diff(x) > 0).all() or not (np.diff(y) > 0).all():
        raise ValueError("Temperature scale values must increase strictly in both columns.")
    direction = scale.get("direction", "nominal_to_corrected")
    if direction not in ("nominal_to_corrected", "corrected_to_nominal"):
        raise ValueError("Unknown temperature scale direction.")
    return {
        "scale_name": str(scale.get("scale_name", "")),
        "direction": direction,
        "pre_scaled_values": x.tolist(),
        "scaled_values": y.tolist(),
    }


def list_daqmx_scales() -> tuple[str, ...]:
    """Return saved local NI-DAQmx scale names.

    Returns:
        (tuple[str, ...]): Sorted MAX scale names.

    Raises:
        RuntimeError: If NI-DAQmx or its local driver is unavailable.
    """
    try:
        from nidaqmx.system import System

        return tuple(sorted(System.local().scales.scale_names))
    except Exception as exc:
        raise RuntimeError(f"Could not list NI-DAQmx scales: {exc}") from exc


def load_daqmx_temperature_scale(name: str) -> dict:
    """Extract a saved NI table scale as a kelvin-to-kelvin snapshot.

    Args:
        name (str): Saved MAX scale name, interpreted as nominal to corrected kelvin.

    Returns:
        (dict): Validated paired table values and their source scale name.

    Raises:
        RuntimeError: If NI-DAQmx cannot read the scale.
        ValueError: If the scale is not a reversible temperature table.
    """
    try:
        from nidaqmx.constants import ScaleType
        from nidaqmx.scale import Scale

        scale = Scale(name)
        if scale.scale_type != ScaleType.TABLE:
            raise ValueError(f"Scale {name!r} is not an NI-DAQmx table scale.")
        values = {
            "scale_name": name,
            "pre_scaled_values": scale.table_pre_scaled_vals,
            "scaled_values": scale.table_scaled_vals,
        }
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not read NI-DAQmx scale {name!r}: {exc}") from exc
    return normalise_temperature_scale(values)
