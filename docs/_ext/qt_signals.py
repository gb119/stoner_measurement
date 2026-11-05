"""Render Qt's binding-generated signal help as literal text in autodoc."""


def remember_signal_help(app, _what, name, obj, _options, lines):
    """Identify binding-generated help before Napoleon parses attribute types."""
    cls = type(obj)
    if (
        cls.__name__ == "pyqtSignal"
        and cls.__module__ in {"PyQt5.QtCore", "PyQt6.QtCore"}
        and lines
        and lines[0].startswith("pyqtSignal(")
    ):
        pending = app.env.temp_data.setdefault("stoner_native_signal_help", {})
        pending[name] = list(lines)


def format_signal_help(app, _what, name, _obj, _options, lines):
    """Restore native help as literal text after Napoleon; retain authored RST."""
    pending = app.env.temp_data.get("stoner_native_signal_help", {})
    native_help = pending.pop(name, None)
    if native_help is not None:
        lines[:] = [
            "Qt signal.",
            "",
            ".. code-block:: text",
            "",
            *(f"   {line}" for line in native_help),
            "",
        ]


def setup(app):
    """Keep native binding help separate from authored Google-style fields."""
    app.connect("autodoc-process-docstring", remember_signal_help, priority=250)
    app.connect("autodoc-process-docstring", format_signal_help, priority=750)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
