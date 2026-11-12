"""NI table extraction and validation without a local NI runtime."""

import sys
from types import SimpleNamespace

import pytest

from stoner_measurement.instruments.temperature_scales import (
    list_daqmx_scales,
    load_daqmx_temperature_scale,
    normalise_temperature_scale,
)


def test_extract_saved_table_and_list_without_opening_tasks(monkeypatch):
    monkeypatch.setitem(sys.modules, "nidaqmx", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "nidaqmx.system",
        SimpleNamespace(
            System=SimpleNamespace(
                local=lambda: SimpleNamespace(scales=SimpleNamespace(scale_names=["z", "a"]))
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules, "nidaqmx.constants", SimpleNamespace(ScaleType=SimpleNamespace(TABLE=10450))
    )
    monkeypatch.setitem(
        sys.modules,
        "nidaqmx.scale",
        SimpleNamespace(
            Scale=lambda name: SimpleNamespace(
                scale_type=10450, table_pre_scaled_vals=[20, 10], table_scaled_vals=[22, 11]
            )
        ),
    )
    assert list_daqmx_scales() == ("a", "z")
    assert load_daqmx_temperature_scale("a") == {
        "scale_name": "a",
        "direction": "nominal_to_corrected",
        "pre_scaled_values": [10.0, 20.0],
        "scaled_values": [11.0, 22.0],
    }


@pytest.mark.parametrize(
    ("x", "y"),
    [
        ([1], [2]),
        ([1, 2], [2]),
        ([1, 1], [2, 3]),
        ([1, 2], [3, 3]),
        ([1, 2, 3], [1, 3, 2]),
        ([1, float("nan")], [2, 3]),
        ([-1, 2], [2, 3]),
        ([1, 2], [2, float("inf")]),
    ],
)
def test_reject_invalid_or_noninvertible_tables(x, y):
    with pytest.raises(ValueError):
        normalise_temperature_scale({"pre_scaled_values": x, "scaled_values": y})


def test_non_table_scale_is_rejected(monkeypatch):
    monkeypatch.setitem(sys.modules, "nidaqmx", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules, "nidaqmx.constants", SimpleNamespace(ScaleType=SimpleNamespace(TABLE=10450))
    )
    monkeypatch.setitem(
        sys.modules,
        "nidaqmx.scale",
        SimpleNamespace(Scale=lambda name: SimpleNamespace(scale_type=10447)),
    )
    with pytest.raises(ValueError, match="not an NI-DAQmx table scale"):
        load_daqmx_temperature_scale("linear")


def test_missing_ni_runtime_is_reported(monkeypatch):
    monkeypatch.setitem(sys.modules, "nidaqmx.system", None)
    with pytest.raises(RuntimeError, match="Could not list"):
        list_daqmx_scales()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
