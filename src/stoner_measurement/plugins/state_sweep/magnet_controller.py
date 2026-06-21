"""Magnet-controller-backed state-sweep plugin."""

from __future__ import annotations

from stoner_measurement.plugins.state._magnet_controller_plugin import (
    MagnetControllerPluginMixin,
)
from stoner_measurement.plugins.state_sweep.base import StateSweepPlugin


class MagnetControllerSweepPlugin(MagnetControllerPluginMixin, StateSweepPlugin):
    """Sweep the magnet field continuously according to a sweep generator.

    Use this plugin when you want the magnetic field to change continuously,
    with data collected while the field is moving rather than only at a list
    of settled set-points. This is useful for ramp-based measurements and for
    experiments where timing relative to the ramp matters.

    In the configuration tabs, you choose the magnet-controller settings and
    the sweep generator that defines how the field should evolve with time.
    The plugin then follows that generator while reporting the current control
    value back to the sequence framework.

    Attributes documented on the mixin and base classes control the detailed
    ramp behaviour, tolerances, and engine integration for more technical
    script-oriented use.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._init_magnet_controller_plugin()

    @property
    def name(self) -> str:
        return "Magnet Controller"

    @property
    def state_name(self) -> str:
        return "Control Value"

    @property
    def units(self) -> str:
        return "T"

    def __next__(self) -> bool:
        """Advance the sweep using the configured sweep generator semantics."""
        return super().__next__()

    def to_json(self) -> dict[str, object]:
        data = super().to_json()
        data.update(self._magnet_settings_to_json())
        return data

    def _restore_from_json(self, data: dict[str, object]) -> None:
        super()._restore_from_json(data)
        self._restore_magnet_settings(data)
