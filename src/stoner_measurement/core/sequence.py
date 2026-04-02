"""Sequence data model.

A :class:`Sequence` is an ordered list of :class:`SequenceStep` objects.
Each step carries a *plugin name* (identifying which plugin handles it)
and an arbitrary *parameters* dictionary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SequenceStep:
    """A single step within a measurement sequence.

    Attributes
    ----------
    plugin_name:
        The name of the plugin that will execute this step.
    parameters:
        Arbitrary key/value configuration for the step.
    """

    plugin_name: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the step to a plain dictionary."""
        return {"plugin_name": self.plugin_name, "parameters": dict(self.parameters)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SequenceStep:
        """Deserialise a step from a plain dictionary."""
        return cls(
            plugin_name=str(data["plugin_name"]),
            parameters=dict(data.get("parameters", {})),
        )


class Sequence:
    """An ordered collection of :class:`SequenceStep` objects.

    Parameters
    ----------
    steps:
        Optional initial list of steps.
    """

    def __init__(self, steps: list[SequenceStep] | None = None) -> None:
        self._steps: list[SequenceStep] = list(steps) if steps else []

    # ------------------------------------------------------------------
    # Sequence-like interface
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._steps)

    def __iter__(self):
        return iter(self._steps)

    def __getitem__(self, index: int) -> SequenceStep:
        return self._steps[index]

    def append(self, step: SequenceStep) -> None:
        """Append *step* to the end of the sequence."""
        self._steps.append(step)

    def remove(self, index: int) -> SequenceStep:
        """Remove and return the step at *index*."""
        return self._steps.pop(index)

    def clear(self) -> None:
        """Remove all steps."""
        self._steps.clear()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise the whole sequence."""
        return {"steps": [s.to_dict() for s in self._steps]}

    @classmethod
    def from_dict(cls, data: dict) -> Sequence:
        """Deserialise a sequence from a plain dictionary."""
        steps = [SequenceStep.from_dict(s) for s in data.get("steps", [])]
        return cls(steps)
