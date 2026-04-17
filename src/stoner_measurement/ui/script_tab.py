"""Script editor tab combining a tabbed Python editor panel and an interactive console."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QSplitter, QTabWidget, QVBoxLayout, QWidget

from stoner_measurement.ui.console_widget import ConsoleWidget
from stoner_measurement.ui.editor_widget import EditorWidget

# ---------------------------------------------------------------------------
# Per-script pane
# ---------------------------------------------------------------------------


class _ScriptPane(QWidget):
    """Single script editor pane with associated file-state tracking.

    Wraps an :class:`~stoner_measurement.ui.editor_widget.EditorWidget` and
    tracks three pieces of state per script:

    * ``path`` — the file-system path to the saved script (``None`` for unsaved).
    * ``dirty`` — set whenever the editor content changes after the last save or
      load; cleared by :meth:`mark_clean` or :meth:`set_text`.
    * ``customised`` — set when the user manually edits content in the pane;
      cleared by :meth:`set_text` (programmatic replacement resets the flag).

    Args:
        parent (QWidget | None):
            Optional parent widget.

    Attributes:
        editor (EditorWidget): The embedded Python source editor.
    """

    dirty_changed = pyqtSignal(bool)
    """Emitted when the dirty flag transitions between ``True`` and ``False``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._editor = EditorWidget(self)
        self._path: Path | None = None
        self._dirty: bool = False
        self._customised: bool = False
        self._suppress_dirty: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._editor)
        self.setLayout(layout)

        self._editor.document().contentsChanged.connect(self._on_contents_changed)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def editor(self) -> EditorWidget:
        """The embedded Python source editor.

        Returns:
            (EditorWidget):
                The editor widget for this pane.
        """
        return self._editor

    @property
    def path(self) -> Path | None:
        """File-system path for this script, or ``None`` when unsaved.

        Returns:
            (Path | None):
                The current file path.
        """
        return self._path

    @path.setter
    def path(self, value: Path | None) -> None:
        self._path = value

    @property
    def dirty(self) -> bool:
        """``True`` when the script has unsaved changes.

        Returns:
            (bool):
                The current dirty state.
        """
        return self._dirty

    @property
    def customised(self) -> bool:
        """``True`` when the user has edited a sequence-generated script.

        Returns:
            (bool):
                The current customised state.
        """
        return self._customised

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_text(self, text: str) -> None:
        """Replace the editor content with *text* without marking the pane dirty.

        Both the dirty and customised flags are cleared by this method, since
        a programmatic replacement resets any user-edit state.

        Args:
            text (str):
                New content for the editor.
        """
        self._suppress_dirty = True
        try:
            self._editor.set_text(text)
        finally:
            self._suppress_dirty = False
        self._customised = False
        if self._dirty:
            self._dirty = False
            self.dirty_changed.emit(False)

    def mark_clean(self) -> None:
        """Clear the dirty flag (e.g. after a successful save).

        The customised flag is not affected by this method.
        """
        if self._dirty:
            self._dirty = False
            self.dirty_changed.emit(False)

    def mark_customised(self) -> None:
        """Set the customised flag, indicating the user has edited generated code."""
        self._customised = True

    def tab_title(self) -> str:
        """Return the appropriate title for this pane's tab.

        Returns:
            (str):
                ``"<filename> *"`` when dirty, ``"<filename>"`` otherwise.
                Unsaved panes use ``"Untitled"`` as the filename.
        """
        name = self._path.name if self._path else "Untitled"
        return f"{name} *" if self._dirty else name

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _on_contents_changed(self) -> None:
        """Mark the pane dirty and customised when the editor content changes."""
        if self._suppress_dirty:
            return
        self._customised = True
        if not self._dirty:
            self._dirty = True
            self.dirty_changed.emit(True)


# ---------------------------------------------------------------------------
# ScriptTab — tabbed editor + console
# ---------------------------------------------------------------------------


class ScriptTab(QWidget):
    """Container widget with a tabbed Python editor panel and an interactive console.

    The layout places a :class:`QTabWidget` of
    :class:`_ScriptPane` instances (top, ~70 %) above a shared
    :class:`~stoner_measurement.ui.console_widget.ConsoleWidget` (bottom, ~30 %),
    separated by a draggable :class:`QSplitter`.

    Each inner tab holds one ``_ScriptPane`` which wraps an
    :class:`~stoner_measurement.ui.editor_widget.EditorWidget` and tracks the
    file path, dirty flag, and customised flag for that script.

    Args:
        parent (QWidget | None):
            Optional parent widget.

    Attributes:
        console (ConsoleWidget): The shared interactive console / output area.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> app = QApplication.instance() or QApplication([])
        >>> tab = ScriptTab()
        >>> tab.text
        ''
        >>> tab.set_text("# my sequence")
        >>> tab.text
        '# my sequence'
    """

    current_tab_changed = pyqtSignal()
    """Emitted when the active script tab changes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._script_tabs = QTabWidget(self)
        self._script_tabs.setTabsClosable(True)
        self._script_tabs.tabCloseRequested.connect(self._on_close_tab)
        self._script_tabs.currentChanged.connect(lambda _: self.current_tab_changed.emit())
        self._tab_counter = 0

        self.console = ConsoleWidget(self)

        self._splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._splitter.addWidget(self._script_tabs)
        self._splitter.addWidget(self.console)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._splitter)
        self.setLayout(layout)

        self._splitter.setStretchFactor(0, 7)
        self._splitter.setStretchFactor(1, 3)

        # Start with one empty untitled tab
        self.new_tab()

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    def new_tab(self) -> _ScriptPane:
        """Create a new empty untitled script tab and make it the active tab.

        Returns:
            (_ScriptPane):
                The newly created pane.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> tab = ScriptTab()
            >>> initial_count = tab._script_tabs.count()
            >>> pane = tab.new_tab()
            >>> tab._script_tabs.count() == initial_count + 1
            True
        """
        self._tab_counter += 1
        pane = _ScriptPane(self)
        title = f"Untitled {self._tab_counter}"
        pane.dirty_changed.connect(lambda _dirty, p=pane: self._update_tab_title(p))
        self._script_tabs.addTab(pane, title)
        self._script_tabs.setCurrentWidget(pane)
        return pane

    def add_tab(
        self,
        text: str,
        path: Path | None = None,
        customised: bool = False,
    ) -> _ScriptPane:
        """Add a new script tab pre-loaded with *text*.

        Args:
            text (str):
                Initial content for the editor.

        Keyword Parameters:
            path (Path | None):
                File-system path to associate with the script. When provided the
                tab title uses ``path.name``; otherwise ``"Untitled N"`` is used.
            customised (bool):
                When ``True``, the pane's customised flag is set immediately
                (e.g. for scripts generated from a sequence that the user may
                subsequently edit).

        Returns:
            (_ScriptPane):
                The newly created pane.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> tab = ScriptTab()
            >>> pane = tab.add_tab("x = 1", customised=True)
            >>> pane.customised
            True
            >>> pane.dirty
            False
        """
        pane = self.new_tab()
        pane.path = path
        pane.set_text(text)
        if customised:
            pane.mark_customised()
        self._update_tab_title(pane)
        return pane

    def current_pane(self) -> _ScriptPane | None:
        """Return the currently active :class:`_ScriptPane`, or ``None``.

        Returns:
            (_ScriptPane | None):
                The active pane, or ``None`` when no tabs exist.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> tab = ScriptTab()
            >>> tab.current_pane() is not None
            True
        """
        widget = self._script_tabs.currentWidget()
        return widget if isinstance(widget, _ScriptPane) else None

    # ------------------------------------------------------------------
    # Public API (compatibility + convenience)
    # ------------------------------------------------------------------

    @property
    def editor(self) -> EditorWidget:
        """The :class:`~stoner_measurement.ui.editor_widget.EditorWidget` in the active tab.

        Returns:
            (EditorWidget):
                The active pane's editor widget.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> tab = ScriptTab()
            >>> from stoner_measurement.ui.editor_widget import EditorWidget
            >>> isinstance(tab.editor, EditorWidget)
            True
        """
        pane = self.current_pane()
        if pane is not None:
            return pane.editor
        # Defensive fallback — should never happen in normal usage.
        return EditorWidget()

    @property
    def text(self) -> str:
        """Current content of the active script editor.

        Returns:
            (str):
                The active pane's plain text.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> tab = ScriptTab()
            >>> tab.text
            ''
        """
        pane = self.current_pane()
        return pane.editor.text() if pane is not None else ""

    def set_text(self, text: str) -> None:
        """Replace the active pane's editor content with *text*.

        Args:
            text (str):
                New content for the editor.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> tab = ScriptTab()
            >>> tab.set_text("x = 42")
            >>> tab.text
            'x = 42'
        """
        pane = self.current_pane()
        if pane is not None:
            pane.set_text(text)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _update_tab_title(self, pane: _ScriptPane) -> None:
        """Refresh the tab label for *pane* to reflect its current state."""
        index = self._find_pane_index(pane)
        if index >= 0:
            self._script_tabs.setTabText(index, pane.tab_title())

    def _find_pane_index(self, pane: _ScriptPane) -> int:
        """Return the tab index for *pane*, or ``-1`` if not found."""
        for i in range(self._script_tabs.count()):
            if self._script_tabs.widget(i) is pane:
                return i
        return -1

    def _on_close_tab(self, index: int) -> None:
        """Handle a tab-close request."""
        pane = self._script_tabs.widget(index)
        if isinstance(pane, _ScriptPane) and pane.dirty:
            name = pane.path.name if pane.path else "Untitled"
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"'{name}' has unsaved changes. Close without saving?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Discard:
                return

        if self._script_tabs.count() == 1:
            # Keep at least one tab — just reset it instead of removing.
            if isinstance(pane, _ScriptPane):
                pane.set_text("")
                pane.path = None
                self._tab_counter += 1
                self._script_tabs.setTabText(0, f"Untitled {self._tab_counter}")
            return

        self._script_tabs.removeTab(index)
