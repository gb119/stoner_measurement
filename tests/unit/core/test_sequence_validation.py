"""Preflight diagnostics without configuration-expression execution."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.core.validation import ValidationError, validate_expression, validate_sequence
from stoner_measurement.plugins.trace import DummyPlugin
from stoner_measurement.plugins.trace.k6221_pulse_delta import Keithley6221PulseDeltaPlugin
from stoner_measurement.scan.list_generator import ListScanGenerator


def test_expression_names_respect_scopes_and_do_not_execute(caplog):
    function = MagicMock()
    namespace = {"source": function, "np": object(), "offset": 2}
    validate_expression("[np.sin(x + offset) for x in source()]", namespace, label="scan")
    validate_expression("(lambda y: y + offset)(1)", namespace, label="scan")
    function.assert_not_called()
    assert not caplog.records
    validate_expression("np.sin(offest)", namespace, label="current")
    assert "offest" in caplog.text
    assert "current" in caplog.text
    with pytest.raises(ValidationError, match="invalid expression"):
        validate_expression("offset **", namespace, label="current")


def test_validation_collects_failures_with_step_names():
    plugins = [
        SimpleNamespace(instance_name=name, validate=MagicMock(side_effect=ValidationError("bad")))
        for name in ("first", "second")
    ]
    with pytest.raises(ValidationError, match="first: bad\nsecond: bad"):
        validate_sequence(plugins, {})
    for plugin in plugins:
        plugin.validate.assert_called_once()


def test_pulse_literals_fail_but_expressions_are_never_evaluated(qapp):
    plugin = Keithley6221PulseDeltaPlugin()
    plugin.sequence_engine = SimpleNamespace(_namespace={"later": object()})
    plugin.eval_float = MagicMock(side_effect=AssertionError("must not evaluate"))
    plugin._pulse_width = 0.025
    with pytest.raises(ValidationError, match="pulse_width"):
        plugin.validate()
    plugin._pulse_width = "later()"
    plugin._pulse_source_delay = 0.005
    assert plugin.validate()
    plugin.eval_float.assert_not_called()
    plugin.scan_generator = ListScanGenerator(stages=[("later **", True)], parent=plugin)
    with pytest.raises(ValidationError, match="point 1"):
        validate_sequence([plugin], plugin.engine_namespace)


def test_generated_preflight_blocks_connections_in_nested_sequence(qapp):
    engine = SequenceEngine()
    plugin = Keithley6221PulseDeltaPlugin()
    plugin.instance_name = "pulse"
    plugin._pulse_width = 0.025
    plugin.connect = MagicMock()
    parent = DummyPlugin()
    parent.instance_name = "parent_step"
    parent.connect = MagicMock()
    try:
        engine.add_plugin("pulse", plugin)
        engine.add_plugin("parent_step", parent)
        assert parent.validate() is True
        code = engine.generate_sequence_code([(parent, [(plugin, [])])], {})
        namespace = dict(engine.namespace)
        namespace["select_display_plugin"] = lambda *_: None
        with pytest.raises(ValidationError, match="pulse"):
            exec(code, namespace)
        plugin.connect.assert_not_called()
        parent.connect.assert_not_called()
    finally:
        engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
