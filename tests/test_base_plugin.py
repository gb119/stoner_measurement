"""Tests for BasePlugin default method implementations."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.base_plugin import (
    BasePlugin,
    _docstring_to_html,
    _inline_format,
    _render_section_items,
    _rst_role_to_short,
)


class _MinimalPlugin(BasePlugin):
    # No docstring — exercises the no-About-tab code path.

    @property
    def name(self) -> str:
        return "Minimal"


class _DocumentedPlugin(BasePlugin):
    """A well-documented test plugin for verifying About-tab generation."""

    @property
    def name(self) -> str:
        return "Documented"


# ---------------------------------------------------------------------------
# Tests for the docstring-to-HTML helper functions
# ---------------------------------------------------------------------------


class TestRstRoleToShort:
    """Unit tests for the _rst_role_to_short helper."""

    def _match(self, text: str):
        import re
        pattern = re.compile(r":[a-z]+:`([^`]*)`")
        return pattern.search(text)

    def test_simple_name(self):
        m = self._match(":meth:`execute`")
        import re
        class _FakeMatch:
            def group(self, n):
                return "execute"
        assert _rst_role_to_short(_FakeMatch()) == "execute"

    def test_tilde_strips_module_prefix(self):
        import re
        pattern = re.compile(r":[a-z]+:`([^`]*)`")
        text = ":meth:`~foo.bar.Baz.method`"
        m = pattern.search(text)
        assert _rst_role_to_short(m) == "method"

    def test_dotted_name_keeps_last(self):
        import re
        pattern = re.compile(r":[a-z]+:`([^`]*)`")
        m = pattern.search(":class:`stoner_measurement.plugins.base_plugin.BasePlugin`")
        assert _rst_role_to_short(m) == "BasePlugin"

    def test_no_tilde_no_dots_unchanged(self):
        import re
        pattern = re.compile(r":[a-z]+:`([^`]*)`")
        m = pattern.search(":attr:`name`")
        assert _rst_role_to_short(m) == "name"


class TestInlineFormat:
    """Unit tests for _inline_format."""

    def test_plain_text_escaped(self):
        assert _inline_format("a < b & c > d") == "a &lt; b &amp; c &gt; d"

    def test_double_backtick_to_code(self):
        assert _inline_format("use ``foo``") == "use <code>foo</code>"

    def test_bold_to_b(self):
        assert _inline_format("**bold**") == "<b>bold</b>"

    def test_italic_to_em(self):
        assert _inline_format("*italic*") == "<em>italic</em>"

    def test_single_backtick_to_code(self):
        assert _inline_format("`code`") == "<code>code</code>"

    def test_rst_role_stripped_to_short_name(self):
        html = _inline_format(":meth:`~foo.bar.execute`")
        assert html == "execute"

    def test_rst_role_in_sentence(self):
        html = _inline_format("call :meth:`run` now")
        assert html == "call run now"

    def test_code_content_html_escaped(self):
        html = _inline_format("``a < b``")
        assert html == "<code>a &lt; b</code>"

    def test_multiple_markup_tokens(self):
        html = _inline_format("``x`` and **bold** and *em*")
        assert "<code>x</code>" in html
        assert "<b>bold</b>" in html
        assert "<em>em</em>" in html


class TestRenderSectionItems:
    """Unit tests for _render_section_items."""

    def test_single_item_no_description(self):
        lines = ["    foo (str):"]
        html = _render_section_items(lines)
        assert "<dl>" in html
        assert "foo (str)" in html

    def test_item_with_description(self):
        lines = ["    delay (float):", "        Seconds to wait."]
        html = _render_section_items(lines)
        assert "<dt>" in html
        assert "<dd>" in html
        assert "Seconds to wait." in html

    def test_multiple_items(self):
        lines = [
            "    alpha (float):",
            "        First.",
            "    beta (int):",
            "        Second.",
        ]
        html = _render_section_items(lines)
        assert "alpha (float)" in html
        assert "beta (int)" in html

    def test_empty_lines_ignored(self):
        lines = ["", "    item (str):", ""]
        html = _render_section_items(lines)
        assert "item (str)" in html

    def test_empty_input_returns_empty(self):
        assert _render_section_items([]) == ""

    def test_all_blank_returns_empty(self):
        assert _render_section_items(["   ", "  "]) == ""


class TestDocstringToHtml:
    """Unit tests for _docstring_to_html."""

    def test_heading_uses_plugin_name(self):
        html = _docstring_to_html("MyPlugin", "A simple plugin.")
        assert "<h3>MyPlugin</h3>" in html

    def test_summary_wrapped_in_paragraph(self):
        html = _docstring_to_html("P", "A simple plugin.")
        assert "<p>" in html
        assert "A simple plugin." in html

    def test_developer_sections_omitted(self):
        doc = "Summary.\n\nExamples:\n    >>> pass\n"
        html = _docstring_to_html("P", doc)
        assert ">>> pass" not in html
        assert "Examples" not in html

    def test_keyword_parameters_omitted(self):
        doc = "Summary.\n\nKeyword Parameters:\n    parent (QObject):\n        The parent.\n"
        html = _docstring_to_html("P", doc)
        assert "parent" not in html

    def test_attributes_section_shown(self):
        doc = "Summary.\n\nAttributes:\n    value (int):\n        The value.\n"
        html = _docstring_to_html("P", doc)
        assert "value" in html
        assert "<h4>" in html

    def test_notes_section_shown(self):
        doc = "Summary.\n\nNotes:\n    An important note.\n"
        html = _docstring_to_html("P", doc)
        assert "Notes" in html

    def test_code_block_after_double_colon(self):
        doc = "Example::\n\n    result = foo()\n"
        html = _docstring_to_html("P", doc)
        assert "<pre><code>" in html
        assert "result = foo()" in html

    def test_bullet_list_rendered_as_ul(self):
        doc = "Features:\n\n* First item\n* Second item\n"
        html = _docstring_to_html("P", doc)
        assert "<ul>" in html
        assert "<li>" in html
        assert "First item" in html

    def test_inline_code_in_paragraph(self):
        doc = "Use ``delay_expr`` to set the delay."
        html = _docstring_to_html("P", doc)
        assert "<code>delay_expr</code>" in html

    def test_sentence_ending_in_colon_not_section(self):
        doc = "The class provides:\n\n* Feature one\n"
        html = _docstring_to_html("P", doc)
        # "The class provides:" should be a paragraph, not a section header
        assert "<p>" in html
        assert "<h4>" not in html or "The class provides" not in html

    def test_html_special_chars_escaped(self):
        doc = "Use a < b for comparison."
        html = _docstring_to_html("P", doc)
        assert "&lt;" in html
        assert "<b>" not in html or "a" not in html  # no spurious bold

class TestBasePluginDefaults:
    def test_config_widget_returns_label(self, qapp):
        plugin = _MinimalPlugin()
        from PyQt6.QtWidgets import QLabel
        widget = plugin.config_widget()
        assert isinstance(widget, QLabel)
        assert "Minimal" in widget.text()

    def test_config_tabs_wraps_config_widget(self, qapp):
        plugin = _MinimalPlugin()
        tabs = plugin.config_tabs()
        assert isinstance(tabs, list)
        assert len(tabs) == 2
        title, widget = tabs[0]
        assert title == "Minimal"
        from PyQt6.QtWidgets import QWidget
        assert isinstance(widget, QWidget)

    def test_config_tabs_title_matches_name(self, qapp):
        plugin = _MinimalPlugin()
        tabs = plugin.config_tabs()
        assert tabs[0][0] == plugin.name

    def test_config_tabs_general_tab_is_last(self, qapp):
        plugin = _MinimalPlugin()
        tabs = plugin.config_tabs()
        assert tabs[-1][0] == "General"

    def test_about_html_returns_none_for_undocumented_plugin(self, qapp):
        plugin = _MinimalPlugin()
        assert plugin._about_html() is None

    def test_about_html_returns_string_for_documented_plugin(self, qapp):
        plugin = _DocumentedPlugin()
        html = plugin._about_html()
        assert isinstance(html, str)
        assert "<h3>" in html
        assert "Documented" in html

    def test_config_tabs_includes_about_tab_for_documented_plugin(self, qapp):
        plugin = _DocumentedPlugin()
        tabs = plugin.config_tabs()
        tab_titles = [t[0] for t in tabs]
        assert any("About" in t for t in tab_titles)

    def test_config_tabs_about_tab_is_last_for_documented_plugin(self, qapp):
        plugin = _DocumentedPlugin()
        tabs = plugin.config_tabs()
        assert "About" in tabs[-1][0]

    def test_monitor_widget_returns_none(self):
        plugin = _MinimalPlugin()
        assert plugin.monitor_widget() is None

    def test_monitor_widget_accepts_parent(self, qapp):
        from PyQt6.QtWidgets import QWidget
        plugin = _MinimalPlugin()
        parent = QWidget()
        assert plugin.monitor_widget(parent=parent) is None

    def test_sequence_engine_default_none(self):
        plugin = _MinimalPlugin()
        assert plugin.sequence_engine is None

    def test_engine_namespace_detached_returns_empty_dict(self):
        plugin = _MinimalPlugin()
        assert plugin.engine_namespace == {}


class TestBasePluginEval:
    """Tests for BasePlugin.eval()."""

    def test_eval_raises_when_detached(self):
        plugin = _MinimalPlugin()
        with pytest.raises(RuntimeError, match="not attached to a sequence engine"):
            plugin.eval("1 + 1")

    def test_eval_raises_syntax_error(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        with pytest.raises(SyntaxError):
            plugin.eval("def")
        engine.shutdown()

    def test_eval_raises_exception_from_expression(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        with pytest.raises(ZeroDivisionError):
            plugin.eval("1/0")
        engine.shutdown()

    def test_eval_simple_arithmetic(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        assert plugin.eval("1 + 1") == 2
        engine.shutdown()

    def test_eval_with_engine_namespace(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        engine._namespace["_x"] = 7
        assert plugin.eval("_x * 6") == 42
        engine.shutdown()

    def test_eval_numpy_sin_with_engine(self, qapp):
        import numpy as np

        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        result = plugin.eval("sin(0.0)")
        assert abs(result - np.sin(0.0)) < 1e-12
        engine.shutdown()

    def test_eval_numpy_sqrt_with_engine(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)
        result = plugin.eval("sqrt(9.0)")
        assert abs(result - 3.0) < 1e-12
        engine.shutdown()

    def test_eval_does_not_pollute_namespace_with_print(self, qapp):
        """eval() must not permanently overwrite 'print' in the engine namespace.

        asteval.Interpreter.__init__ unconditionally injects its own ``_printer``
        into the supplied symtable.  Without the save/restore guard in
        ``BasePlugin.eval()``, all subsequent ``print()`` calls in the engine
        namespace would use asteval's writer (the terminal) instead of the
        redirected ``sys.stdout``.
        """

        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)

        assert "print" not in engine.namespace, "namespace should not have 'print' before eval"
        plugin.eval("1 + 1")
        assert "print" not in engine.namespace, "eval() must not leave 'print' in the namespace"

        engine.shutdown()

    def test_eval_preserves_user_defined_print_in_namespace(self, qapp):
        """eval() must restore a user-set 'print' after asteval overwrites it."""
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = _MinimalPlugin()
        engine.add_plugin("minimal", plugin)

        def custom_print(*a, **kw):
            pass
        # Use the live namespace dict (engine.namespace returns a copy).
        plugin.engine_namespace["print"] = custom_print

        plugin.eval("1 + 1")

        assert plugin.engine_namespace.get("print") is custom_print, (
            "eval() must restore a pre-existing 'print' to the namespace"
        )

        engine.shutdown()


class TestGenerateInstantiationCode:
    def test_returns_list_of_strings(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert isinstance(lines, list)
        assert all(isinstance(line, str) for line in lines)

    def test_guard_uses_instance_name(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert lines[0] == "if 'minimal' not in globals():"

    def test_guard_uses_custom_instance_name(self):
        plugin = _MinimalPlugin()
        plugin.instance_name = "my_plugin"
        lines = plugin.generate_instantiation_code()
        assert lines[0] == "if 'my_plugin' not in globals():"

    def test_reconstruction_uses_base_plugin_from_json(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert "_BasePlugin.from_json" in lines[1]

    def test_reconstruction_uses_json_loads(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert "_json.loads" not in lines[1]

    def test_json_payload_contains_class_path(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        cls = type(plugin)
        expected_class = f"{cls.__module__}:{cls.__qualname__}"
        assert expected_class in lines[1]

    def test_json_payload_contains_instance_name(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert "minimal" in lines[1]

    def test_ends_with_blank_separator(self):
        plugin = _MinimalPlugin()
        lines = plugin.generate_instantiation_code()
        assert lines[-1] == ""

