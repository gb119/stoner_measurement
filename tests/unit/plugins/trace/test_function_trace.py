"""Tests for the user-defined synthetic trace plugin."""

from __future__ import annotations

import numpy as np
import pytest

from stoner_measurement.core import COLUMN_ROLE_X, COLUMN_ROLE_Y, COLUMN_ROLE_Z
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace import FunctionTracePlugin, TraceStatus
from stoner_measurement.ui.editor_widget import EditorWidget


def _set_scan_values(plugin: FunctionTracePlugin, monkeypatch, values) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    monkeypatch.setattr(plugin.scan_generator, "generate", lambda: x)
    return x


def test_calculates_multichannel_dataframe_from_scan_values(qapp, monkeypatch):
    plugin = FunctionTracePlugin()
    x = _set_scan_values(plugin, monkeypatch, np.linspace(0.0, 1.0, 5))
    plugin.function_code = """\
def calculate_data(x):
    return pd.DataFrame({"squared": x**2, "sine": np.sin(x)})
"""

    result = plugin.measure({})[plugin.name]

    np.testing.assert_allclose(result.df["x"], x)
    np.testing.assert_allclose(result.df["squared"], x**2)
    np.testing.assert_allclose(result.df["sine"], np.sin(x))
    assert result.column_roles == {
        "x": COLUMN_ROLE_X,
        "squared": COLUMN_ROLE_Y,
        "sine": COLUMN_ROLE_Z,
    }
    assert plugin.status is TraceStatus.DATA_AVAILABLE


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("value = 1", "calculate_data"),
        ("def calculate_data(x): return x", "DataFrame"),
        (
            "def calculate_data(x): return pd.DataFrame({'y': x[:-1]})",
            "lengths must match",
        ),
        (
            "def calculate_data(x): return pd.DataFrame({'x': x, 'y': x})",
            "reserved",
        ),
        (
            "def calculate_data(x): return pd.DataFrame({'label': ['a'] * len(x)})",
            "numeric",
        ),
    ],
)
def test_rejects_invalid_function_results(qapp, monkeypatch, code, error):
    plugin = FunctionTracePlugin()
    _set_scan_values(plugin, monkeypatch, [0.0, 1.0, 2.0])
    plugin.function_code = code

    with pytest.raises((TypeError, ValueError), match=error):
        plugin.measure({})
    assert plugin.status is TraceStatus.ERROR
    assert plugin.data == {}


def test_function_source_and_scan_generator_round_trip(qapp):
    plugin = FunctionTracePlugin()
    plugin.function_code = "def calculate_data(x):\n    return pd.DataFrame({'y': 2*x})\n"

    restored = BasePlugin.from_json(plugin.to_json())

    assert isinstance(restored, FunctionTracePlugin)
    assert restored.function_code == plugin.function_code
    assert type(restored.scan_generator) is type(plugin.scan_generator)


def test_config_tabs_use_standard_scan_page_and_compact_shared_editor(qapp, managed_qt_widget):
    plugin = FunctionTracePlugin()
    tabs = plugin.config_tabs()
    for _title, page in tabs:
        managed_qt_widget(page)

    assert [title for title, _page in tabs] == ["Scan", "Function", "About"]
    editor = tabs[1][1].findChild(EditorWidget, "functionTraceEditor")
    assert editor is not None
    assert editor.maximumHeight() == 260
    assert "calculate_data" in editor.text()


def test_editor_updates_source_and_marks_syntax_errors(qapp, managed_qt_widget):
    plugin = FunctionTracePlugin()
    function_page = managed_qt_widget(plugin.config_tabs()[1][1])
    editor = function_page.findChild(EditorWidget, "functionTraceEditor")

    editor.set_text("def calculate_data(x):\n    return pd.DataFrame({'y': x})\n")
    assert plugin.function_code == editor.text()
    assert editor.syntax_error_line is None

    editor.set_text("def calculate_data(x)\n    return x\n")
    assert editor.syntax_error_line == 1


def test_user_function_receives_copy_of_scan_values(qapp, monkeypatch):
    plugin = FunctionTracePlugin()
    x = _set_scan_values(plugin, monkeypatch, [1.0, 2.0, 3.0])
    plugin.function_code = """\
def calculate_data(x):
    x[:] = 0
    return pd.DataFrame({"y": x})
"""

    plugin.measure({})

    np.testing.assert_allclose(x, [1.0, 2.0, 3.0])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
