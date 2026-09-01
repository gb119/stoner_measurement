"""Tests for reusable Curve Fit function-module discovery and editing."""

from __future__ import annotations

import sys

import pytest

from stoner_measurement.plugins.transform import fit_function_library as library_module
from stoner_measurement.plugins.transform.curve_fit import CurveFitPlugin
from stoner_measurement.plugins.transform.fit_function_library import (
    FitFunctionLibraryWidget,
    FitFunctionTab,
    discover_fit_function_modules,
    prepare_user_module_path,
    validate_fit_function_source,
)
from stoner_measurement.ui.editor_widget import EditorWidget

VALID_SOURCE = """\
\"\"\"A reusable model.\"\"\"
import numpy as np
from math import sqrt

def helper(value):
    return sqrt(value)

def fit(x, amplitude):
    return amplitude * np.asarray(x)

def p0(x, y):
    return (helper(float(y[0])),)
"""


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("def helper(x, y): return x", "fit()"),
        ("def fit(x): return x", "at least two"),
        (
            "def fit(x, a): return a*x\ndef p0(x): return (1,)",
            "exactly two",
        ),
        (
            "value = 2\ndef fit(x, a): return value*x",
            "Only imports",
        ),
        ("def fit(x, a) return a*x", "Syntax error"),
    ],
)
def test_validation_rejects_invalid_library_modules(source, message):
    assert message in (validate_fit_function_source(source) or "")


def test_validation_accepts_imports_helpers_fit_and_p0():
    assert validate_fit_function_source(VALID_SOURCE) is None


def test_discovery_builds_qualified_names_and_excludes_invalid_modules(tmp_path):
    standard_root = tmp_path / "standard_functions"
    user_root = tmp_path / "user_functions"
    (standard_root / "peaks").mkdir(parents=True)
    user_root.mkdir()
    (standard_root / "peaks" / "gaussian.py").write_text(VALID_SOURCE, encoding="utf-8")
    (standard_root / "invalid.py").write_text("def helper(x): return x", encoding="utf-8")
    (user_root / "linear.py").write_text("def fit(x, a): return a*x\n", encoding="utf-8")

    modules = discover_fit_function_modules(
        standard_root=standard_root,
        user_root=user_root,
    )

    assert [module.module_name for module in modules] == [
        "stoner_measurement.plugins.transform.standard_functions.peaks.gaussian",
        "user_functions.linear",
    ]
    assert modules[0].docstring == "A reusable model."
    assert modules[1].docstring == ""


def test_bundled_library_contains_common_models():
    names = {module.display_parts[-1] for module in discover_fit_function_modules()}
    assert {"linear", "gaussian", "lorentzian", "exponential_decay"} <= names


def test_prepare_user_module_path_creates_package_chain(tmp_path):
    root = tmp_path / "user_functions"
    target, module_name = prepare_user_module_path(
        root / "transport" / "hall_effect.py",
        root,
    )

    assert target == root / "transport" / "hall_effect.py"
    assert module_name == "user_functions.transport.hall_effect"
    assert (root / "__init__.py").is_file()
    assert (root / "transport" / "__init__.py").is_file()


@pytest.mark.parametrize(
    "relative_path",
    ["bad-name.py", "folder/bad name.py", "class.py", "__init__.py", "fit.txt"],
)
def test_prepare_user_module_path_rejects_invalid_destinations(tmp_path, relative_path):
    root = tmp_path / "user_functions"
    with pytest.raises(ValueError):
        prepare_user_module_path(root / relative_path, root)


def test_prepare_user_module_path_rejects_file_outside_package(tmp_path):
    with pytest.raises(ValueError, match="inside"):
        prepare_user_module_path(tmp_path / "elsewhere" / "fit.py", tmp_path / "user_functions")


def test_library_load_copies_complete_module_source(qapp, managed_qt_widget, tmp_path):
    standard_root = tmp_path / "standard_functions"
    standard_root.mkdir()
    source_path = standard_root / "model.py"
    source_path.write_text(VALID_SOURCE, encoding="utf-8")
    editor = managed_qt_widget(EditorWidget())
    library = managed_qt_widget(
        FitFunctionLibraryWidget(
            editor,
            standard_root=standard_root,
            user_root=tmp_path / "user_functions",
        )
    )
    activated: list[str] = []
    library.module_activated.connect(activated.append)
    item = library._module_items[  # noqa: SLF001
        "stoner_measurement.plugins.transform.standard_functions.model"
    ]
    library.tree.setCurrentItem(item)

    library.load_button.click()

    assert editor.text() == VALID_SOURCE
    assert activated == ["stoner_measurement.plugins.transform.standard_functions.model"]


def test_library_tooltip_uses_docstring_then_falls_back_to_path(qapp, managed_qt_widget, tmp_path):
    standard_root = tmp_path / "standard_functions"
    standard_root.mkdir()
    documented = standard_root / "documented.py"
    undocumented = standard_root / "undocumented.py"
    documented.write_text(VALID_SOURCE, encoding="utf-8")
    undocumented.write_text("def fit(x, a): return a*x\n", encoding="utf-8")
    editor = managed_qt_widget(EditorWidget())
    library = managed_qt_widget(
        FitFunctionLibraryWidget(
            editor,
            standard_root=standard_root,
            user_root=tmp_path / "user_functions",
        )
    )

    documented_item = library._module_items[  # noqa: SLF001
        "stoner_measurement.plugins.transform.standard_functions.documented"
    ]
    undocumented_item = library._module_items[  # noqa: SLF001
        "stoner_measurement.plugins.transform.standard_functions.undocumented"
    ]

    assert documented_item.toolTip(0) == "A reusable model."
    assert undocumented_item.toolTip(0) == str(undocumented)


def test_library_buttons_are_above_tree(qapp, managed_qt_widget, tmp_path):
    editor = managed_qt_widget(EditorWidget())
    library = managed_qt_widget(
        FitFunctionLibraryWidget(
            editor,
            standard_root=tmp_path / "standard_functions",
            user_root=tmp_path / "user_functions",
        )
    )
    library.resize(500, 300)
    library.show()
    qapp.processEvents()

    assert library.load_button.geometry().bottom() < library.tree.geometry().top()
    assert library.save_button.geometry().bottom() < library.tree.geometry().top()
    assert library.refresh_button.geometry().bottom() < library.tree.geometry().top()


def test_library_save_writes_module_and_refreshes_tree(
    qapp, managed_qt_widget, monkeypatch, tmp_path
):
    user_root = tmp_path / "user_functions"
    editor = managed_qt_widget(EditorWidget())
    editor.set_text(VALID_SOURCE)
    library = managed_qt_widget(
        FitFunctionLibraryWidget(
            editor,
            standard_root=tmp_path / "standard_functions",
            user_root=user_root,
        )
    )
    target = user_root / "peaks" / "custom.py"
    monkeypatch.setattr(
        library_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(target), "Python modules (*.py)"),
    )
    activated: list[str] = []
    library.module_activated.connect(activated.append)

    library.save_button.click()

    assert target.read_text(encoding="utf-8") == VALID_SOURCE
    assert (user_root / "__init__.py").is_file()
    assert (user_root / "peaks" / "__init__.py").is_file()
    assert "user_functions.peaks.custom" in library._module_items  # noqa: SLF001
    assert activated == ["user_functions.peaks.custom"]


def test_fit_function_tab_caps_editor_height(qapp, managed_qt_widget):
    tab = managed_qt_widget(FitFunctionTab())
    editor = EditorWidget(tab)
    tab.set_editor(editor)
    tab.resize(600, 1200)
    tab.show()
    qapp.processEvents()
    line_height = editor.fontMetrics().lineSpacing()
    expected = (
        line_height * 25 + round(editor.document().documentMargin() * 2) + editor.frameWidth() * 2
    )
    assert editor.height() == expected

    tab.resize(600, 300)
    qapp.processEvents()
    assert editor.height() <= 200


def test_module_context_supports_relative_imports(monkeypatch, tmp_path):
    user_root = tmp_path / "user_functions"
    target, _ = prepare_user_module_path(user_root / "models" / "linear.py", user_root)
    target.write_text("", encoding="utf-8")
    (target.parent / "helpers.py").write_text(
        "def scale(x, value):\n    return x * value\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(library_module, "user_functions_root", lambda: user_root)
    monkeypatch.setattr(sys, "path", list(sys.path))
    plugin = CurveFitPlugin()
    plugin.fit_module_name = "user_functions.models.linear"
    plugin.fit_code = (
        "from .helpers import scale\n\ndef fit(x, amplitude):\n    return scale(x, amplitude)\n"
    )

    fit, p0 = plugin._compile_fit_code()  # noqa: SLF001

    assert fit(3.0, 2.0) == 6.0
    assert p0 is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
