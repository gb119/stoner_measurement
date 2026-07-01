"""Focused tests for TransformPlugin behavior."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.transform import TransformPlugin


class _ScaleTransform(TransformPlugin):
    """TransformPlugin that scales 'y' by a factor of 3."""

    @property
    def name(self) -> str:
        return "Scale"

    @property
    def required_inputs(self) -> list[str]:
        return ["y"]

    @property
    def output_names(self) -> list[str]:
        return ["y_scaled"]

    def transform(self, data: dict[str, object]) -> dict[str, object]:
        return {"y_scaled": [v * 3 for v in data["y"]]}


class TestTransformPlugin:
    def test_plugin_type(self, qapp):
        assert _ScaleTransform().plugin_type == "transform"

    def test_has_lifecycle_false(self, qapp):
        assert _ScaleTransform().has_lifecycle is False

    def test_required_inputs(self, qapp):
        assert _ScaleTransform().required_inputs == ["y"]

    def test_output_names(self, qapp):
        assert _ScaleTransform().output_names == ["y_scaled"]

    def test_description_default(self, qapp):
        assert _ScaleTransform().description == ""

    def test_generate_action_code_calls_run(self, qapp):
        p = _ScaleTransform()
        p.instance_name = "scale"
        lines = p.generate_action_code(1, [], lambda s, i: [])
        assert any("scale.run({})" in ln for ln in lines)

    def test_generate_action_code_not_commented(self, qapp):
        p = _ScaleTransform()
        lines = p.generate_action_code(1, [], lambda s, i: [])
        code_lines = [ln for ln in lines if ln.strip()]
        assert all(not ln.strip().startswith("#") for ln in code_lines)

    def test_transform_returns_dict(self, qapp):
        p = _ScaleTransform()
        result = p.transform({"y": [1.0, 2.0, 3.0]})
        assert result == {"y_scaled": [3.0, 6.0, 9.0]}

    def test_validate_inputs_passes(self, qapp):
        p = _ScaleTransform()
        p.validate_inputs({"y": [1.0]})

    def test_validate_inputs_raises_on_missing(self, qapp):
        p = _ScaleTransform()
        with pytest.raises(ValueError, match="y"):
            p.validate_inputs({"x": [1.0]})

    def test_validate_inputs_raises_lists_all_missing(self, qapp):
        class _Multi(TransformPlugin):
            @property
            def name(self):
                return "Multi"

            @property
            def required_inputs(self):
                return ["a", "b"]

            @property
            def output_names(self):
                return ["c"]

            def transform(self, data):
                return {"c": data["a"]}

        p = _Multi()
        with pytest.raises(ValueError):
            p.validate_inputs({})

    def test_run_returns_result(self, qapp):
        p = _ScaleTransform()
        result = p.run({"y": [2.0, 4.0]})
        assert result == {"y_scaled": [6.0, 12.0]}

    def test_run_emits_transform_complete(self, qapp):
        p = _ScaleTransform()
        received = []
        p.transform_complete.connect(received.append)
        p.run({"y": [1.0]})
        assert received == [{"y_scaled": [3.0]}]

    def test_run_raises_on_missing_inputs(self, qapp):
        p = _ScaleTransform()
        with pytest.raises(ValueError):
            p.run({})

    def test_transform_complete_signal(self, qapp):
        p = _ScaleTransform()
        received = []
        p.transform_complete.connect(received.append)
        p.transform_complete.emit({"out": 1.0})
        assert received == [{"out": 1.0}]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
