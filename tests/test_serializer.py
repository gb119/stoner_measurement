"""Tests for JSON serialisation and deserialisation of scan generators, plugins, and sequences."""

from __future__ import annotations

import json

import pytest

from stoner_measurement.scan import (
    BaseScanGenerator,
    FunctionScanGenerator,
    SteppedScanGenerator,
    WaveformType,
)


class TestSteppedScanGeneratorJson:
    """Round-trip tests for SteppedScanGenerator JSON serialisation."""

    def test_to_json_type_field(self, qapp):
        gen = SteppedScanGenerator()
        d = gen.to_json()
        assert d["type"] == "SteppedScanGenerator"

    def test_to_json_start_field(self, qapp):
        gen = SteppedScanGenerator(start=3.5)
        d = gen.to_json()
        assert d["start"] == 3.5

    def test_to_json_stages_field(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.25, True), (2.0, 0.5, False)])
        d = gen.to_json()
        assert d["stages"] == [[1.0, 0.25, True], [2.0, 0.5, False]]

    def test_to_json_empty_stages(self, qapp):
        gen = SteppedScanGenerator(start=5.0)
        d = gen.to_json()
        assert d["stages"] == []

    def test_from_json_data_round_trip(self, qapp):
        gen = SteppedScanGenerator(start=1.0, stages=[(2.0, 0.5, True), (3.0, 0.25, False)])
        d = gen.to_json()
        restored = SteppedScanGenerator._from_json_data(d)
        assert restored.start == gen.start
        assert restored.stages == gen.stages

    def test_base_from_json_dispatches_to_stepped(self, qapp):
        gen = SteppedScanGenerator(start=0.5, stages=[(1.0, 0.25, True)])
        restored = BaseScanGenerator.from_json(gen.to_json())
        assert isinstance(restored, SteppedScanGenerator)
        assert restored.start == 0.5
        assert restored.stages == [(1.0, 0.25, True)]

    def test_from_json_defaults_when_keys_absent(self, qapp):
        d = {"type": "SteppedScanGenerator"}
        gen = BaseScanGenerator.from_json(d)
        assert isinstance(gen, SteppedScanGenerator)
        assert gen.start == 0.0
        assert gen.stages == []


class TestFunctionScanGeneratorJson:
    """Round-trip tests for FunctionScanGenerator JSON serialisation."""

    def test_to_json_type_field(self, qapp):
        gen = FunctionScanGenerator()
        d = gen.to_json()
        assert d["type"] == "FunctionScanGenerator"

    def test_to_json_all_fields_present(self, qapp):
        gen = FunctionScanGenerator()
        d = gen.to_json()
        for key in ("waveform", "amplitude", "offset", "phase", "exponent", "periods", "num_points"):
            assert key in d

    def test_to_json_waveform_as_string(self, qapp):
        gen = FunctionScanGenerator(waveform=WaveformType.TRIANGLE)
        d = gen.to_json()
        assert d["waveform"] == "Triangle"

    def test_round_trip_preserves_all_parameters(self, qapp):
        gen = FunctionScanGenerator(
            waveform=WaveformType.SQUARE,
            amplitude=2.5,
            offset=0.5,
            phase=45.0,
            exponent=2.0,
            periods=3.0,
            num_points=50,
        )
        d = gen.to_json()
        restored = FunctionScanGenerator._from_json_data(d)
        assert restored.waveform is WaveformType.SQUARE
        assert restored.amplitude == 2.5
        assert restored.offset == 0.5
        assert restored.phase == 45.0
        assert restored.exponent == 2.0
        assert restored.periods == 3.0
        assert restored.num_points == 50

    def test_base_from_json_dispatches_to_function(self, qapp):
        gen = FunctionScanGenerator(amplitude=3.0, num_points=20)
        restored = BaseScanGenerator.from_json(gen.to_json())
        assert isinstance(restored, FunctionScanGenerator)
        assert restored.amplitude == 3.0
        assert restored.num_points == 20

    def test_from_json_defaults_when_keys_absent(self, qapp):
        d = {"type": "FunctionScanGenerator"}
        gen = BaseScanGenerator.from_json(d)
        assert isinstance(gen, FunctionScanGenerator)
        assert gen.amplitude == 1.0
        assert gen.exponent == 1.0
        assert gen.num_points == 100


class TestBaseScanGeneratorFromJson:
    """Tests for BaseScanGenerator.from_json dispatch and error handling."""

    def test_unknown_type_raises_value_error(self, qapp):
        with pytest.raises(ValueError, match="Unknown scan generator type"):
            BaseScanGenerator.from_json({"type": "NonExistentGenerator"})

    def test_missing_type_raises_value_error(self, qapp):
        with pytest.raises(ValueError, match="Unknown scan generator type"):
            BaseScanGenerator.from_json({})


class TestBasePluginJson:
    """Tests for BasePlugin.to_json / from_json on simple plugins."""

    def test_to_json_contains_class_type_instance_name(self, qapp):
        from stoner_measurement.plugins.trace import DummyPlugin

        plugin = DummyPlugin()
        d = plugin.to_json()
        assert d["type"] == "trace"
        assert "class" in d
        assert d["instance_name"] == plugin.instance_name
        assert "DummyPlugin" in d["class"]

    def test_class_field_has_module_colon_classname_format(self, qapp):
        from stoner_measurement.plugins.trace import DummyPlugin

        plugin = DummyPlugin()
        d = plugin.to_json()
        assert ":" in d["class"]
        module_part, class_part = d["class"].split(":", 1)
        assert "." in module_part  # module path contains dots
        assert class_part == "DummyPlugin"

    def test_from_json_recreates_correct_class(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin
        from stoner_measurement.plugins.trace import DummyPlugin

        plugin = DummyPlugin()
        restored = BasePlugin.from_json(plugin.to_json())
        assert isinstance(restored, DummyPlugin)

    def test_from_json_restores_instance_name(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin
        from stoner_measurement.plugins.trace import DummyPlugin

        plugin = DummyPlugin()
        plugin.instance_name = "my_custom_name"
        restored = BasePlugin.from_json(plugin.to_json())
        assert restored.instance_name == "my_custom_name"

    def test_from_json_missing_class_key_raises(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        with pytest.raises(KeyError):
            BasePlugin.from_json({"type": "trace", "instance_name": "x"})


class TestTracePluginJson:
    """Tests for TracePlugin JSON serialisation, including scan generator."""

    def test_to_json_includes_scan_generator(self, qapp):
        from stoner_measurement.plugins.trace import DummyPlugin

        plugin = DummyPlugin()
        d = plugin.to_json()
        assert "scan_generator" in d
        assert d["scan_generator"]["type"] == "SteppedScanGenerator"

    def test_round_trip_preserves_scan_generator_type(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin
        from stoner_measurement.plugins.trace import DummyPlugin

        plugin = DummyPlugin()
        plugin.set_scan_generator_class(FunctionScanGenerator)
        restored = BasePlugin.from_json(plugin.to_json())
        assert isinstance(restored.scan_generator, FunctionScanGenerator)

    def test_round_trip_preserves_stepped_generator_params(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin
        from stoner_measurement.plugins.trace import DummyPlugin

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.5, stages=[(2.0, 0.5, True)], parent=plugin
        )
        restored = BasePlugin.from_json(plugin.to_json())
        assert isinstance(restored.scan_generator, SteppedScanGenerator)
        assert restored.scan_generator.start == 0.5
        assert restored.scan_generator.stages == [(2.0, 0.5, True)]


class TestStateControlPluginJson:
    """Tests for StateControlPlugin JSON serialisation."""

    def test_to_json_type_is_state(self, qapp):
        from stoner_measurement.plugins.state_control import CounterPlugin

        plugin = CounterPlugin()
        d = plugin.to_json()
        assert d["type"] == "state"

    def test_to_json_includes_scan_generator(self, qapp):
        from stoner_measurement.plugins.state_control import CounterPlugin

        plugin = CounterPlugin()
        d = plugin.to_json()
        assert "scan_generator" in d

    def test_round_trip_restores_scan_generator_params(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin
        from stoner_measurement.plugins.state_control import CounterPlugin

        plugin = CounterPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=1.0, stages=[(5.0, 1.0, True)], parent=plugin
        )
        restored = BasePlugin.from_json(plugin.to_json())
        assert isinstance(restored.scan_generator, SteppedScanGenerator)
        assert restored.scan_generator.start == 1.0
        assert restored.scan_generator.stages == [(5.0, 1.0, True)]


class TestSequenceSerializer:
    """Tests for sequence_to_json / sequence_from_json."""

    def test_sequence_to_json_has_version(self, qapp):
        from stoner_measurement.core.serializer import sequence_to_json

        data = sequence_to_json([])
        assert "version" in data
        assert isinstance(data["version"], str)

    def test_sequence_to_json_version_matches_package(self, qapp):
        import stoner_measurement
        from stoner_measurement.core.serializer import sequence_to_json

        data = sequence_to_json([])
        assert data["version"] == stoner_measurement.__version__

    def test_sequence_to_json_empty_steps(self, qapp):
        from stoner_measurement.core.serializer import sequence_to_json

        data = sequence_to_json([])
        assert data["steps"] == []

    def test_sequence_to_json_single_leaf_step(self, qapp):
        from stoner_measurement.core.serializer import sequence_to_json
        from stoner_measurement.plugins.trace import DummyPlugin

        plugin = DummyPlugin()
        data = sequence_to_json([plugin])
        assert len(data["steps"]) == 1
        assert "plugin" in data["steps"][0]
        assert "sub_steps" not in data["steps"][0]

    def test_sequence_to_json_nested_step(self, qapp):
        from stoner_measurement.core.serializer import sequence_to_json
        from stoner_measurement.plugins.state_control import CounterPlugin
        from stoner_measurement.plugins.trace import DummyPlugin

        outer = CounterPlugin()
        inner = DummyPlugin()
        data = sequence_to_json([(outer, [inner])])
        step = data["steps"][0]
        assert "sub_steps" in step
        assert len(step["sub_steps"]) == 1

    def test_sequence_from_json_empty(self, qapp):
        from stoner_measurement.core.serializer import sequence_from_json

        steps = sequence_from_json({"version": "0.1.0", "steps": []})
        assert steps == []

    def test_sequence_from_json_single_leaf(self, qapp):
        from stoner_measurement.core.serializer import sequence_from_json, sequence_to_json
        from stoner_measurement.plugins.trace import DummyPlugin

        plugin = DummyPlugin()
        plugin.instance_name = "test_dummy"
        data = sequence_to_json([plugin])
        steps = sequence_from_json(data)
        assert len(steps) == 1
        from stoner_measurement.plugins.trace import DummyPlugin as _D

        assert isinstance(steps[0], _D)
        assert steps[0].instance_name == "test_dummy"

    def test_sequence_from_json_preserves_nesting(self, qapp):
        from stoner_measurement.core.serializer import sequence_from_json, sequence_to_json
        from stoner_measurement.plugins.state_control import CounterPlugin
        from stoner_measurement.plugins.trace import DummyPlugin

        outer = CounterPlugin()
        outer.instance_name = "outer_counter"
        inner = DummyPlugin()
        inner.instance_name = "inner_dummy"
        data = sequence_to_json([(outer, [inner])])
        steps = sequence_from_json(data)
        assert len(steps) == 1
        restored_outer, sub_steps = steps[0]
        assert isinstance(restored_outer, CounterPlugin)
        assert restored_outer.instance_name == "outer_counter"
        assert len(sub_steps) == 1
        assert isinstance(sub_steps[0], DummyPlugin)
        assert sub_steps[0].instance_name == "inner_dummy"

    def test_sequence_round_trip_multiple_steps(self, qapp):
        from stoner_measurement.core.serializer import sequence_from_json, sequence_to_json
        from stoner_measurement.plugins.trace import DummyPlugin

        plugins = [DummyPlugin(), DummyPlugin(), DummyPlugin()]
        for i, p in enumerate(plugins):
            p.instance_name = f"dummy_{i}"
        data = sequence_to_json(plugins)
        steps = sequence_from_json(data)
        assert len(steps) == 3
        for i, step in enumerate(steps):
            assert step.instance_name == f"dummy_{i}"


class TestJsonTextRoundTrip:
    """Tests that verify JSON text serialisation — i.e. the dict can be rendered to
    a JSON string and then parsed back to produce an identical result.

    This mirrors the real on-disk path: ``json.dumps`` then ``json.loads``.
    """

    def test_stepped_generator_json_text_round_trip(self, qapp):
        gen = SteppedScanGenerator(start=1.5, stages=[(3.0, 0.5, True), (5.0, 0.25, False)])
        text = json.dumps(gen.to_json())
        restored = BaseScanGenerator.from_json(json.loads(text))
        assert isinstance(restored, SteppedScanGenerator)
        assert restored.start == gen.start
        assert restored.stages == gen.stages

    def test_function_generator_json_text_round_trip(self, qapp):
        gen = FunctionScanGenerator(
            waveform=WaveformType.SAWTOOTH, amplitude=2.0, offset=-1.0,
            phase=30.0, periods=2.5, num_points=64,
        )
        text = json.dumps(gen.to_json())
        restored = BaseScanGenerator.from_json(json.loads(text))
        assert isinstance(restored, FunctionScanGenerator)
        assert restored.waveform is WaveformType.SAWTOOTH
        assert restored.amplitude == 2.0
        assert restored.offset == -1.0
        assert restored.phase == 30.0
        assert restored.periods == 2.5
        assert restored.num_points == 64

    def test_trace_plugin_json_text_round_trip(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin
        from stoner_measurement.plugins.trace import DummyPlugin

        plugin = DummyPlugin()
        plugin.instance_name = "my_trace"
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(2.0, 1.0, True)], parent=plugin
        )
        text = json.dumps(plugin.to_json())
        restored = BasePlugin.from_json(json.loads(text))
        assert isinstance(restored, DummyPlugin)
        assert restored.instance_name == "my_trace"
        assert isinstance(restored.scan_generator, SteppedScanGenerator)
        assert restored.scan_generator.start == 0.0
        assert restored.scan_generator.stages == [(2.0, 1.0, True)]

    def test_state_control_plugin_json_text_round_trip(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin
        from stoner_measurement.plugins.state_control import CounterPlugin

        plugin = CounterPlugin()
        plugin.instance_name = "my_counter"
        plugin.scan_generator = SteppedScanGenerator(
            start=-1.0, stages=[(1.0, 0.5, True)], parent=plugin
        )
        text = json.dumps(plugin.to_json())
        restored = BasePlugin.from_json(json.loads(text))
        assert isinstance(restored, CounterPlugin)
        assert restored.instance_name == "my_counter"
        assert isinstance(restored.scan_generator, SteppedScanGenerator)
        assert restored.scan_generator.start == -1.0
        assert restored.scan_generator.stages == [(1.0, 0.5, True)]

    def test_full_sequence_json_text_round_trip(self, qapp):
        from stoner_measurement.core.serializer import sequence_from_json, sequence_to_json
        from stoner_measurement.plugins.state_control import CounterPlugin
        from stoner_measurement.plugins.trace import DummyPlugin

        outer = CounterPlugin()
        outer.instance_name = "field"
        outer.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(10.0, 1.0, True)], parent=outer
        )
        inner = DummyPlugin()
        inner.instance_name = "iv_curve"
        inner.scan_generator = FunctionScanGenerator(amplitude=0.1, num_points=50, parent=inner)
        standalone = DummyPlugin()
        standalone.instance_name = "calibration"

        original_steps = [(outer, [inner]), standalone]
        text = json.dumps(sequence_to_json(original_steps))
        restored_steps = sequence_from_json(json.loads(text))

        assert len(restored_steps) == 2

        # Check the nested outer step.
        restored_outer, restored_sub = restored_steps[0]
        assert isinstance(restored_outer, CounterPlugin)
        assert restored_outer.instance_name == "field"
        assert isinstance(restored_outer.scan_generator, SteppedScanGenerator)
        assert restored_outer.scan_generator.stages == [(10.0, 1.0, True)]

        # Check the inner sub-step.
        assert len(restored_sub) == 1
        assert isinstance(restored_sub[0], DummyPlugin)
        assert restored_sub[0].instance_name == "iv_curve"
        assert isinstance(restored_sub[0].scan_generator, FunctionScanGenerator)
        assert restored_sub[0].scan_generator.amplitude == 0.1
        assert restored_sub[0].scan_generator.num_points == 50

        # Check the standalone leaf step.
        assert isinstance(restored_steps[1], DummyPlugin)
        assert restored_steps[1].instance_name == "calibration"


class TestSequenceEqualityRoundTrip:
    """Verify that a round-trip through JSON yields a structurally identical sequence.

    The canonical comparison is ``original.to_json() == restored.to_json()``:
    if both sides produce the same dict, the plugin and its scan generator
    have been faithfully recreated.
    """

    def _assert_step_equal(self, original, restored) -> None:
        """Recursively compare two _SequenceStep values by their to_json() output."""
        if isinstance(original, tuple):
            orig_plugin, orig_sub = original
            rest_plugin, rest_sub = restored
            assert orig_plugin.to_json() == rest_plugin.to_json()
            assert len(orig_sub) == len(rest_sub)
            for o, r in zip(orig_sub, rest_sub):
                self._assert_step_equal(o, r)
        else:
            assert original.to_json() == restored.to_json()

    def test_flat_sequence_equality(self, qapp):
        from stoner_measurement.core.serializer import sequence_from_json, sequence_to_json
        from stoner_measurement.plugins.trace import DummyPlugin

        steps = [DummyPlugin(), DummyPlugin()]
        steps[0].instance_name = "a"
        steps[1].instance_name = "b"
        steps[1].scan_generator = FunctionScanGenerator(amplitude=3.0, num_points=10)
        restored = sequence_from_json(json.loads(json.dumps(sequence_to_json(steps))))
        assert len(restored) == len(steps)
        for orig, rest in zip(steps, restored):
            self._assert_step_equal(orig, rest)

    def test_nested_sequence_equality(self, qapp):
        from stoner_measurement.core.serializer import sequence_from_json, sequence_to_json
        from stoner_measurement.plugins.state_control import CounterPlugin
        from stoner_measurement.plugins.trace import DummyPlugin

        outer = CounterPlugin()
        outer.instance_name = "sweep"
        outer.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(5.0, 0.5, True), (10.0, 0.5, False)], parent=outer
        )
        inner1 = DummyPlugin()
        inner1.instance_name = "trace_a"
        inner2 = DummyPlugin()
        inner2.instance_name = "trace_b"
        inner2.scan_generator = FunctionScanGenerator(
            waveform=WaveformType.TRIANGLE, amplitude=2.0, num_points=30, parent=inner2
        )

        original = [(outer, [inner1, inner2])]
        text = json.dumps(sequence_to_json(original))
        restored = sequence_from_json(json.loads(text))

        assert len(restored) == 1
        self._assert_step_equal(original[0], restored[0])

    def test_deeply_nested_sequence_equality(self, qapp):
        from stoner_measurement.core.serializer import sequence_from_json, sequence_to_json
        from stoner_measurement.plugins.state_control import CounterPlugin
        from stoner_measurement.plugins.trace import DummyPlugin

        level1 = CounterPlugin()
        level1.instance_name = "outer"
        level2 = CounterPlugin()
        level2.instance_name = "middle"
        level3 = DummyPlugin()
        level3.instance_name = "leaf"

        original = [(level1, [(level2, [level3])])]
        text = json.dumps(sequence_to_json(original))
        restored = sequence_from_json(json.loads(text))

        self._assert_step_equal(original[0], restored[0])
