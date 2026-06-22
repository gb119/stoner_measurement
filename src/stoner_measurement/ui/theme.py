"""Application-wide theme helpers for the Stoner Measurement UI."""

from __future__ import annotations

from qtpy.QtGui import QColor, QPalette
from qtpy.QtWidgets import QApplication

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "window": "#232629",
        "window_text": "#f0f0f0",
        "base": "#1b1d20",
        "alternate_base": "#2a2d31",
        "tooltip_base": "#2a2d31",
        "tooltip_text": "#f0f0f0",
        "text": "#f0f0f0",
        "button": "#2d3136",
        "button_text": "#f0f0f0",
        "bright_text": "#ffffff",
        "highlight": "#3d8bfd",
        "highlighted_text": "#ffffff",
        "link": "#6ea8fe",
        "mid": "#4a4f57",
        "disabled_text": "#8b949e",
        "border": "#5c6370",
        "placeholder_text": "#9aa4af",
        "status_default": "#4b5563",
        "status_running": "#2e7d32",
        "status_paused": "#ef6c00",
        "status_error": "#c62828",
        "validation_error_background": "#4a2226",
        "validation_error_border": "#e57373",
        "muted_text": "#9aa4af",
        "gutter_background": "#2a2d31",
        "gutter_text": "#9aa4af",
        "editor_current_line": "#3a3520",
        "value_display_background": "#111827",
        "value_display_border": "#374151",
        "value_display_text": "#10b981",
        "status_connecting": "#b45309",
        "status_connected": "#166534",
        "status_error_soft": "#7f1d1d",
        "syntax_error_marker": "#d32f2f",
        "plot_background": "#1b1d20",
        "plot_foreground": "#d1d5db",
        "plot_grid": "#4b5563",
        "console_error": "#ff8a80",
        "syntax_keyword": "#82aaff",
        "syntax_builtin": "#c792ea",
        "syntax_string": "#c3e88d",
        "syntax_number": "#f78c6c",
        "syntax_comment": "#7f8c98",
        "log_debug": "#b39ddb",
        "log_info": "#90caf9",
        "log_warning": "#ffcc80",
        "log_error": "#ef9a9a",
        "log_critical": "#ff8a80",
        "tab_disabled_text": "#7f8c98",
        "trace_blue": "#7cb9ff",
        "trace_orange": "#ffb86b",
        "trace_green": "#7ee787",
        "trace_red": "#ff7b72",
        "trace_purple": "#c297ff",
        "trace_brown": "#d2a679",
        "trace_teal": "#5eead4",
        "trace_target": "#f0f0f0",
        "setpoint_trace": "#f5f5f5",
    },
    "light": {
        "window": "#f5f5f5",
        "window_text": "#202124",
        "base": "#ffffff",
        "alternate_base": "#f1f3f4",
        "tooltip_base": "#fffde7",
        "tooltip_text": "#202124",
        "text": "#202124",
        "button": "#e8eaed",
        "button_text": "#202124",
        "bright_text": "#ffffff",
        "highlight": "#1a73e8",
        "highlighted_text": "#ffffff",
        "link": "#1a73e8",
        "mid": "#c4c7c5",
        "disabled_text": "#80868b",
        "border": "#babfc4",
        "placeholder_text": "#80868b",
        "status_default": "#d6d9de",
        "status_running": "#43a047",
        "status_paused": "#fb8c00",
        "status_error": "#e53935",
        "validation_error_background": "#fdeaea",
        "validation_error_border": "#d93025",
        "muted_text": "#5f6368",
        "gutter_background": "#f1f3f4",
        "gutter_text": "#5f6368",
        "editor_current_line": "#fff8e1",
        "value_display_background": "#f8fffb",
        "value_display_border": "#b7d7c6",
        "value_display_text": "#0f9d58",
        "status_connecting": "#f29900",
        "status_connected": "#34a853",
        "status_error_soft": "#f4c7c3",
        "syntax_error_marker": "#d93025",
        "plot_background": "#ffffff",
        "plot_foreground": "#202124",
        "plot_grid": "#d0d7de",
        "console_error": "#c62828",
        "syntax_keyword": "#0b57d0",
        "syntax_builtin": "#7b1fa2",
        "syntax_string": "#2e7d32",
        "syntax_number": "#ef6c00",
        "syntax_comment": "#5f6368",
        "log_debug": "#6a1b9a",
        "log_info": "#1565c0",
        "log_warning": "#b26a00",
        "log_error": "#c62828",
        "log_critical": "#8e0000",
        "tab_disabled_text": "#9aa0a6",
        "trace_blue": "#4169e1",
        "trace_orange": "#d97706",
        "trace_green": "#228b22",
        "trace_red": "#b22222",
        "trace_purple": "#9370db",
        "trace_brown": "#8b4513",
        "trace_teal": "#0f766e",
        "trace_target": "#202124",
        "setpoint_trace": "#202124",
    },
}

DEFAULT_THEME = "dark"
_current_theme_name = DEFAULT_THEME


def colour(name: str) -> str:
    """Return a named theme colour."""
    return THEMES[_current_theme_name][name]


def theme_name() -> str:
    """Return the currently active theme name."""
    return _current_theme_name


def available_themes() -> list[str]:
    """Return the available application theme names."""
    return list(THEMES)


def validation_error_lineedit_stylesheet() -> str:
    """Return a stylesheet for invalid line-edit fields."""
    border = colour("validation_error_border")
    background = colour("validation_error_background")
    text = colour("text")
    return (
        "QLineEdit { "
        f"background-color: {background}; "
        f"border: 1px solid {border}; "
        f"color: {text}; "
        "}"
    )


def status_bar_stylesheet(background_colour: str, foreground_colour: str = "#ffffff") -> str:
    """Return a stylesheet for the application status bar."""
    return (
        "QStatusBar { "
        f"background-color: {background_colour}; "
        f"color: {foreground_colour}; "
        "} "
        "QStatusBar::item { border: none; }"
    )


def indicator_label_stylesheet(background_colour: str, foreground_colour: str) -> str:
    """Return a stylesheet for pill-style status indicator labels."""
    border = colour("border")
    return (
        "QLabel { "
        f"background-color: {background_colour}; "
        f"color: {foreground_colour}; "
        f"border: 1px solid {border}; "
        "border-radius: 4px; "
        "padding: 4px 8px; "
        "}"
    )


def muted_label_stylesheet() -> str:
    """Return a stylesheet for muted informational labels."""
    muted = colour("muted_text")
    return f"QLabel {{ color: {muted}; padding: 8px 4px; }}"


def value_display_frame_stylesheet() -> str:
    """Return a stylesheet for the watch-value display frame."""
    background = colour("value_display_background")
    border = colour("value_display_border")
    return (
        "QFrame {"
        f" background-color: {background};"
        f" border: 2px solid {border};"
        " border-radius: 8px;"
        "}"
    )


def apply_pyqtgraph_dark_theme(plot_item, axis_items: dict[str, object]) -> None:
    """Apply dark-mode colors to a pyqtgraph PlotItem and its axes."""
    foreground = colour("plot_foreground")
    grid_alpha = 64
    grid_opacity = 0.15
    
    for axis in axis_items.values():
        try:
            axis.setPen(foreground)
            axis.setTextPen(foreground)
            axis.setTickPen(foreground)
            axis.setGrid(grid_alpha)
            axis.gridPen = QColor(colour("plot_grid"))
            label_style = {"color": foreground}
            current_label = getattr(axis, "labelText", "") or ""
            if current_label:
                axis.setLabel(current_label, **label_style)
            else:
                axis.labelStyle = label_style
        except AttributeError:
            continue

    try:
        plot_item.getViewBox().setBorder(None)
    except AttributeError:
        pass

    try:
        plot_item.showGrid(x=True, y=True, alpha=grid_opacity)
    except AttributeError:
        pass


def disabled_tab_stylesheet() -> str:
    """Return styling that improves readability of disabled tabs in dark mode."""
    return (
        "QTabBar::tab:disabled { "
        f"color: {colour('tab_disabled_text')}; "
        "}"
    )


def tree_stylesheet() -> str:
    """Return a stylesheet for tree branch guide lines."""
    border = colour("border")
    return f"""
QTreeWidget {{
    show-decoration-selected: 1;
}}
QTreeWidget::branch:has-siblings:!adjoins-item {{
    border-left: 1px solid {border};
    margin-left: 5px;
}}
QTreeWidget::branch:has-siblings:adjoins-item,
QTreeWidget::branch:!has-children:!has-siblings:adjoins-item {{
    border-left: 1px solid {border};
    margin-left: 5px;
    border-bottom: 1px solid {border};
}}
"""


def button_swatch_stylesheet(background_colour: str, foreground_colour: str) -> str:
    """Return a stylesheet for a colour-swatch push button."""
    border = colour("border")
    return (
        "QPushButton { "
        f"background-color: {background_colour}; "
        f"color: {foreground_colour}; "
        f"border: 1px solid {border}; "
        "padding: 2px 6px; "
        "}"
    )


def contrasting_text_colour(background_colour: str) -> str:
    """Return black or white depending on the colour luminance."""
    colour_value = QColor(background_colour)
    if not colour_value.isValid():
        return "#ffffff"
    red, green, blue, _alpha = colour_value.getRgb()
    luminance = (0.299 * red) + (0.587 * green) + (0.114 * blue)
    return "#202020" if luminance > 186 else "#ffffff"


def make_palette() -> QPalette:
    """Create the global application palette for the active theme."""
    palette = QPalette()

    palette.setColor(QPalette.ColorRole.Window, QColor(colour("window")))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colour("window_text")))
    palette.setColor(QPalette.ColorRole.Base, QColor(colour("base")))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colour("alternate_base")))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colour("tooltip_base")))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colour("tooltip_text")))
    palette.setColor(QPalette.ColorRole.Text, QColor(colour("text")))
    palette.setColor(QPalette.ColorRole.Button, QColor(colour("button")))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colour("button_text")))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(colour("bright_text")))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colour("highlight")))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colour("highlighted_text")))
    palette.setColor(QPalette.ColorRole.Link, QColor(colour("link")))
    palette.setColor(QPalette.ColorRole.Mid, QColor(colour("mid")))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(colour("placeholder_text")))

    disabled_text = QColor(colour("disabled_text"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, disabled_text)

    return palette


def theme_stylesheet() -> str:
    """Return a small global stylesheet for theme polish."""
    border = colour("border")
    background = colour("button")
    base = colour("base")
    text = colour("text")
    tooltip_base = colour("tooltip_base")
    tooltip_text = colour("tooltip_text")
    highlight = colour("highlight")
    tree_qss = tree_stylesheet()
    return f"""
QToolTip {{
    color: {tooltip_text};
    background-color: {tooltip_base};
    border: 1px solid {border};
}}

QTabWidget::pane {{
    border: 1px solid {border};
}}

QTabBar::tab {{
    background: {background};
    color: {text};
    border: 1px solid {border};
    padding: 6px 10px;
}}

QTabBar::tab:selected {{
    background: {base};
}}

QHeaderView::section {{
    background-color: {background};
    color: {text};
    border: 1px solid {border};
    padding: 4px;
}}

QSplitter::handle {{
    background-color: {border};
}}

QTreeWidget::item:selected,
QTableWidget::item:selected,
QListWidget::item:selected {{
    background-color: {highlight};
    color: {colour("highlighted_text")};
}}

{tree_qss}
"""


def apply_theme(app: QApplication, theme: str = DEFAULT_THEME) -> None:
    """Apply the named application theme."""
    global _current_theme_name
    theme = theme.lower().strip()
    if theme not in THEMES:
        theme = DEFAULT_THEME
    _current_theme_name = theme
    app.setStyle("Fusion")
    app.setPalette(make_palette())
    app.setStyleSheet(theme_stylesheet())


def apply_dark_theme(app: QApplication) -> None:
    """Apply the application's dark theme."""
    apply_theme(app, "dark")