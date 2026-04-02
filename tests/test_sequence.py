"""Tests for the Sequence and SequenceStep data models."""

from __future__ import annotations

import pytest

from stoner_measurement.core.sequence import Sequence, SequenceStep


class TestSequenceStep:
    def test_creation(self):
        step = SequenceStep(plugin_name="Dummy", parameters={"points": 50})
        assert step.plugin_name == "Dummy"
        assert step.parameters == {"points": 50}

    def test_default_parameters(self):
        step = SequenceStep(plugin_name="Dummy")
        assert step.parameters == {}

    def test_to_dict(self):
        step = SequenceStep(plugin_name="Dummy", parameters={"points": 50})
        d = step.to_dict()
        assert d == {"plugin_name": "Dummy", "parameters": {"points": 50}}

    def test_from_dict(self):
        d = {"plugin_name": "Dummy", "parameters": {"points": 50}}
        step = SequenceStep.from_dict(d)
        assert step.plugin_name == "Dummy"
        assert step.parameters == {"points": 50}

    def test_from_dict_no_parameters(self):
        d = {"plugin_name": "Dummy"}
        step = SequenceStep.from_dict(d)
        assert step.parameters == {}

    def test_roundtrip(self):
        original = SequenceStep(plugin_name="Dummy", parameters={"a": 1, "b": 2})
        restored = SequenceStep.from_dict(original.to_dict())
        assert restored.plugin_name == original.plugin_name
        assert restored.parameters == original.parameters


class TestSequence:
    def test_empty_sequence(self):
        seq = Sequence()
        assert len(seq) == 0

    def test_append_step(self):
        seq = Sequence()
        seq.append(SequenceStep(plugin_name="Dummy"))
        assert len(seq) == 1

    def test_remove_step(self):
        seq = Sequence()
        step = SequenceStep(plugin_name="Dummy")
        seq.append(step)
        removed = seq.remove(0)
        assert removed is step
        assert len(seq) == 0

    def test_remove_invalid_index(self):
        seq = Sequence()
        with pytest.raises(IndexError):
            seq.remove(0)

    def test_clear(self):
        seq = Sequence([SequenceStep("A"), SequenceStep("B")])
        seq.clear()
        assert len(seq) == 0

    def test_iteration(self):
        steps = [SequenceStep("A"), SequenceStep("B"), SequenceStep("C")]
        seq = Sequence(steps)
        assert list(seq) == steps

    def test_getitem(self):
        step = SequenceStep("X")
        seq = Sequence([step])
        assert seq[0] is step

    def test_to_dict(self):
        seq = Sequence([SequenceStep("Dummy", {"points": 10})])
        d = seq.to_dict()
        assert d == {"steps": [{"plugin_name": "Dummy", "parameters": {"points": 10}}]}

    def test_from_dict(self):
        d = {"steps": [{"plugin_name": "Dummy", "parameters": {"points": 10}}]}
        seq = Sequence.from_dict(d)
        assert len(seq) == 1
        assert seq[0].plugin_name == "Dummy"
        assert seq[0].parameters == {"points": 10}

    def test_roundtrip(self):
        original = Sequence(
            [SequenceStep("A", {"x": 1}), SequenceStep("B", {"y": 2})]
        )
        restored = Sequence.from_dict(original.to_dict())
        assert len(restored) == len(original)
        for a, b in zip(original, restored):
            assert a.plugin_name == b.plugin_name
            assert a.parameters == b.parameters
