"""Tests for WCAG colour-contrast helpers."""

from __future__ import annotations

import pytest

from stoner_measurement.ui.theme import contrast_ratio, contrasting_text_colour


@pytest.mark.parametrize(
    "background",
    ["#000000", "#ffffff", "#777777", "#3d8bfd", "#90ee90", "#fff3cd", "#f8d7da"],
)
def test_contrasting_text_colour_meets_wcag_aa(background):
    foreground = contrasting_text_colour(background)

    assert foreground in {"#000000", "#ffffff"}
    assert contrast_ratio(foreground, background) >= 4.5


def test_wcag_reference_contrast_ratios():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#ffffff") == pytest.approx(4.478, rel=1e-3)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
