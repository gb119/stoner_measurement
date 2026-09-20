"""Command plugin for reading detector counts from the diffractometer."""

from __future__ import annotations

import math

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.xray_control import XrayControllerEngine


class ReadDiffractometerCommand(CommandPlugin):
    """Read the X-ray diffractometer and expose its detector counts.

    Use this command beneath a diffractometer scan or after a set command to
    acquire counts using the duration configured in the X-ray control panel.
    It has no instrument-specific settings.
    The preferred diffractometer is reconnected automatically when necessary,
    and the returned detector count is available as ``instance.value`` and as
    the command's **Counts** scalar output.

    Attributes:
        value (float):
            Detector counts from the latest execution; initially NaN.
        instance_name (str):
            Inherited Python identifier for this instance in the Script tab and
            QtConsole.
        comment (str):
            Inherited optional note displayed beside this step.
        sequence_engine (SequenceEngine | None):
            Inherited owning engine and its live namespace; None while
            detached.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        With an instance named ``read_diffractometer`` in the sequence, use the
        QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            read_diffractometer.value
            read_diffractometer.reported_values()
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.value: float = math.nan

    @property
    def name(self) -> str:
        return "Read Diffractometer"

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"xray"})

    def execute(self) -> None:
        engine = XrayControllerEngine.instance()
        if engine.connected_driver is None:
            engine.connect_preferred_driver()
        if engine.connected_driver is None:
            raise RuntimeError("No X-ray diffractometer is connected.")
        state = engine.count()
        if state.snapshot is None:
            raise RuntimeError("The X-ray diffractometer returned no detector reading.")
        self.value = float(state.snapshot.counts)

    def reported_values(self) -> dict[str, str]:
        return {f"{self.instance_name}:Counts": f"{self.instance_name}.value"}

    def reported_value_units(self) -> dict[str, str]:
        """Identify the detector output as a count quantity."""
        return {f"{self.instance_name}:Counts": "counts"}
