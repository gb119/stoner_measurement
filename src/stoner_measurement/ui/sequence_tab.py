"""Sequence-editor tab combining a Python editor and an interactive console."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSplitter, QWidget

from stoner_measurement.ui.console_widget import ConsoleWidget
from stoner_measurement.ui.editor_widget import EditorWidget


class SequenceTab(QWidget):
    """Container widget for the sequence editor and console.

    Lays out an :class:`~stoner_measurement.ui.editor_widget.EditorWidget`
    (top, ~70 %) and a :class:`~stoner_measurement.ui.console_widget.ConsoleWidget`
    (bottom, ~30 %) separated by a draggable :class:`QSplitter`.

    The widget exposes the editor's text so that callers can load or save
    Python sequence scripts.

    Args:
        parent (QWidget | None):
            Optional parent widget.

    Attributes:
        editor (EditorWidget): The Python source editor.
        console (ConsoleWidget): The interactive console / output area.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> app = QApplication.instance() or QApplication([])
        >>> tab = SequenceTab()
        >>> tab.text
        ''
        >>> tab.set_text("# my sequence")
        >>> tab.text
        '# my sequence'
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.editor = EditorWidget(self)
        self.console = ConsoleWidget(self)

        self._splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._splitter.addWidget(self.editor)
        self._splitter.addWidget(self.console)

        from PyQt6.QtWidgets import QVBoxLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._splitter)
        self.setLayout(layout)

        # Set initial proportions (70 / 30)
        self._splitter.setStretchFactor(0, 7)
        self._splitter.setStretchFactor(1, 3)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def text(self) -> str:
        """Current content of the Python editor.

        Returns:
            (str):
                The editor's plain text.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> tab = SequenceTab()
            >>> tab.text
            ''
        """
        return self.editor.text()

    def set_text(self, text: str) -> None:
        """Replace the editor contents with *text*.

        Args:
            text (str):
                New content for the editor.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> tab = SequenceTab()
            >>> tab.set_text("x = 42")
            >>> tab.text
            'x = 42'
        """
        self.editor.set_text(text)
