"""Tests for the SequenceRunner."""

from __future__ import annotations

import pytest

from stoner_measurement.core.runner import SequenceRunner
from stoner_measurement.core.sequence import Sequence, SequenceStep
from stoner_measurement.plugins.dummy import DummyPlugin


class TestSequenceRunner:
    def test_initially_not_running(self, runner):
        assert not runner.is_running

    def test_default_sequence_empty(self, runner):
        assert len(runner.sequence) == 0

    def test_set_sequence(self, runner):
        seq = Sequence([SequenceStep("Dummy", {"points": 5})])
        runner.sequence = seq
        assert runner.sequence is seq

    def test_set_plugins(self, runner):
        plugin = DummyPlugin()
        runner.set_plugins({"Dummy": plugin})
        # No exception — plugins dict is stored internally

    def test_stop_when_not_running(self, runner):
        # Should not raise
        runner.stop()

    def test_data_ready_signal(self, qapp, runner):
        """Run a short sequence and collect data_ready emissions."""
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )  # yields 5 points: 0.0, 0.1, 0.2, 0.3, 0.4
        seq = Sequence([SequenceStep("Dummy", {})])
        runner.sequence = seq
        runner.set_plugins({"Dummy": plugin})

        collected: list[tuple[str, float, float]] = []
        runner.data_ready.connect(lambda name, x, y: collected.append((name, x, y)))

        finished_flags: list[bool] = []
        runner.finished.connect(lambda: finished_flags.append(True))

        runner.start()
        # Wait for the background thread to finish (up to 5 seconds)
        if runner._worker is not None:
            runner._worker.wait(5000)
        # Process any pending Qt events so cross-thread signals are delivered
        qapp.processEvents()

        assert len(collected) == 5
        assert len(finished_flags) == 1
        # All points should be labelled with the plugin name used as trace name
        assert all(name == "Dummy" for name, _x, _y in collected)

    def test_double_start_is_noop(self, qapp, runner):
        """Starting a running runner should be a no-op."""
        seq = Sequence([SequenceStep("Dummy", {"points": 200})])
        runner.sequence = seq
        runner.set_plugins({"Dummy": DummyPlugin()})

        runner.start()
        first_worker = runner._worker
        runner.start()  # second call — should be ignored
        assert runner._worker is first_worker  # same worker

        runner.stop()
        if runner._worker is not None:
            runner._worker.wait(5000)
