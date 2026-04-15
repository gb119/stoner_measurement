"""Python source-code editor widget with syntax highlighting and line numbers."""

from __future__ import annotations

import keyword
import re

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from PyQt6.QtWidgets import QPlainTextEdit, QWidget

# ---------------------------------------------------------------------------
# Syntax highlighter
# ---------------------------------------------------------------------------


class PythonHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for Python source code.

    Highlights keywords, built-in names, string literals, numeric literals,
    and single-line comments using distinct colours.

    Args:
        document (QTextDocument):
            The document to attach the highlighter to.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication, QPlainTextEdit
        >>> app = QApplication.instance() or QApplication([])
        >>> editor = QPlainTextEdit()
        >>> highlighter = PythonHighlighter(editor.document())
    """

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._rules: list[tuple[re.Pattern[str], QTextCharFormat]] = []
        self._build_rules()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_format(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        """Return a QTextCharFormat with the given colour and style flags."""
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(700)
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def _build_rules(self) -> None:
        """Populate self._rules with (pattern, format) pairs."""
        keyword_fmt = self._make_format("#0000ff", bold=True)
        builtin_fmt = self._make_format("#7d26cd")
        string_fmt = self._make_format("#008000", italic=True)
        number_fmt = self._make_format("#b05a00")
        comment_fmt = self._make_format("#808080", italic=True)

        # Keywords
        kw_pattern = r"\b(?:" + "|".join(re.escape(kw) for kw in keyword.kwlist) + r")\b"
        self._rules.append((re.compile(kw_pattern), keyword_fmt))

        # Built-ins
        builtins = [
            "abs", "all", "any", "bin", "bool", "bytes", "callable", "chr",
            "dict", "dir", "divmod", "enumerate", "eval", "exec", "filter",
            "float", "format", "frozenset", "getattr", "globals", "hasattr",
            "hash", "help", "hex", "id", "input", "int", "isinstance",
            "issubclass", "iter", "len", "list", "locals", "map", "max",
            "min", "next", "object", "oct", "open", "ord", "pow", "print",
            "property", "range", "repr", "reversed", "round", "set",
            "setattr", "slice", "sorted", "staticmethod", "str", "sum",
            "super", "tuple", "type", "vars", "zip",
            "None", "True", "False",
        ]
        bi_pattern = r"\b(?:" + "|".join(re.escape(b) for b in builtins) + r")\b"
        self._rules.append((re.compile(bi_pattern), builtin_fmt))

        # Numeric literals
        self._rules.append((re.compile(r"\b\d+(?:\.\d*)?(?:[eE][+-]?\d+)?\b"), number_fmt))

        # Single-quoted strings (non-greedy, on one line)
        self._rules.append((re.compile(r"'[^'\\\n]*(?:\\.[^'\\\n]*)*'"), string_fmt))
        # Double-quoted strings
        self._rules.append((re.compile(r'"[^"\\\n]*(?:\\.[^"\\\n]*)*"'), string_fmt))

        # Single-line comment
        self._rules.append((re.compile(r"#[^\n]*"), comment_fmt))

    # ------------------------------------------------------------------
    # QSyntaxHighlighter interface
    # ------------------------------------------------------------------

    def highlightBlock(self, text: str) -> None:
        """Apply all highlighting rules to *text*."""
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


# ---------------------------------------------------------------------------
# Line-number gutter
# ---------------------------------------------------------------------------

class _LineNumberArea(QWidget):
    """Narrow widget that paints line numbers alongside the editor."""

    def __init__(self, editor: EditorWidget) -> None:
        super().__init__(editor)
        self._editor = editor
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        """Return the required width for the current document."""
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """Delegate painting to the editor."""
        self._editor.paint_line_numbers(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        """Show syntax-error tooltip when hovering the marked line."""
        line_number = self._editor._line_number_for_y(int(event.position().y()))  # noqa: SLF001
        if (
            line_number is not None
            and line_number == self._editor.syntax_error_line
            and self._editor.syntax_error_message
        ):
            self.setToolTip(self._editor.syntax_error_message)
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        """Clear any line-gutter tooltip when the cursor leaves the gutter."""
        self.setToolTip("")
        super().leaveEvent(event)


# ---------------------------------------------------------------------------
# Editor widget
# ---------------------------------------------------------------------------

class EditorWidget(QPlainTextEdit):
    """Plain-text editor with Python syntax highlighting and line numbers.

    Features include:
    * Syntax highlighting via :class:`PythonHighlighter`.
    * A line-number gutter that updates on scroll and content changes.
    * Tab key inserts four spaces instead of a hard tab character.
    * The Return/Enter key auto-indents to match the previous line's leading
      whitespace (with one extra level after lines ending in ``:``)

    Args:
        parent (QWidget | None):
            Optional parent widget.

    Attributes:
        highlighter (PythonHighlighter): The attached syntax highlighter instance.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> app = QApplication.instance() or QApplication([])
        >>> editor = EditorWidget()
        >>> editor.set_text("print('hello')")
        >>> editor.text()
        "print('hello')"
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        font = QFont("Courier New", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)

        self._line_number_area = _LineNumberArea(self)
        self.highlighter = PythonHighlighter(self.document())
        self._syntax_error_line: int | None = None
        self._syntax_error_message: str = ""

        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)

        self._update_line_number_area_width(0)
        self._highlight_current_line()

    # ------------------------------------------------------------------
    # Line-number gutter helpers
    # ------------------------------------------------------------------

    def line_number_area_width(self) -> int:
        """Calculate the pixel width needed for the line-number gutter.

        Returns:
            (int):
                Width in pixels, including a small padding.
        """
        digits = max(1, len(str(self.blockCount())))
        fm = QFontMetrics(self.font())
        return 4 + fm.horizontalAdvance("9") * digits

    def _update_line_number_area_width(self, _block_count: int) -> None:
        """Update editor left margin to accommodate the gutter width."""
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int) -> None:
        """Scroll or repaint the gutter when the viewport scrolls."""
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Resize the gutter when the editor is resized."""
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def paint_line_numbers(self, event) -> None:  # type: ignore[override]
        """Paint line numbers into the gutter widget.

        Args:
            event: The paint event forwarded from :class:`_LineNumberArea`.
        """
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#f0f0f0"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        offset = self.contentOffset()
        top = int(self.blockBoundingGeometry(block).translated(offset).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        line_height = int(self.blockBoundingRect(block).height())

        painter.setPen(QColor("#808080"))
        fm = QFontMetrics(self.font())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if self._syntax_error_line == block_number + 1:
                    marker_size = max(6, min(fm.height() - 2, 10))
                    marker_y = top + max(0, (line_height - marker_size) // 2)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#d32f2f"))
                    painter.drawEllipse(1, marker_y, marker_size, marker_size)
                    painter.setPen(QColor("#808080"))
                number = str(block_number + 1)
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 2,
                    fm.height(),
                    Qt.AlignmentFlag.AlignRight,
                    number,
                )
            block = block.next()
            block_number += 1
            top = bottom
            bottom = top + line_height

    def _highlight_current_line(self) -> None:
        """Highlight the line that contains the text cursor."""
        from PyQt6.QtWidgets import QTextEdit
        extra: list[QTextEdit.ExtraSelection] = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#fffde7"))
            selection.format.setProperty(
                QTextCharFormat.Property.FullWidthSelection, True
            )
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra.append(selection)
        self.setExtraSelections(extra)

    def _line_number_for_y(self, y_pos: int) -> int | None:
        """Return the 1-based line number for a y position in the gutter."""
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        offset = self.contentOffset()
        top = int(self.blockBoundingGeometry(block).translated(offset).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        while block.isValid():
            if block.isVisible() and top <= y_pos <= bottom:
                return block_number + 1
            if top > y_pos:
                break
            block = block.next()
            block_number += 1
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
        return None

    # ------------------------------------------------------------------
    # Key-press overrides
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        """Handle Tab (→ spaces) and Return (→ auto-indent).

        Args:
            event: The key-press event.
        """
        if event.key() == Qt.Key.Key_Tab:
            self.insertPlainText("    ")
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            cursor = self.textCursor()
            block_text = cursor.block().text()
            indent = len(block_text) - len(block_text.lstrip())
            extra = 4 if block_text.rstrip().endswith(":") else 0
            super().keyPressEvent(event)
            self.insertPlainText(" " * (indent + extra))
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def text(self) -> str:
        """Return the full contents of the editor.

        Returns:
            (str):
                The current editor text.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> editor = EditorWidget()
            >>> editor.set_text("x = 1")
            >>> editor.text()
            'x = 1'
        """
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        """Replace the editor contents with *text*.

        Args:
            text (str):
                New content for the editor.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> editor = EditorWidget()
            >>> editor.set_text("y = 2")
            >>> editor.text()
            'y = 2'
        """
        self.setPlainText(text)

    @property
    def syntax_error_line(self) -> int | None:
        """Return the currently marked syntax-error line, if any."""
        return self._syntax_error_line

    @property
    def syntax_error_message(self) -> str:
        """Return the current syntax-error message shown in the gutter tooltip."""
        return self._syntax_error_message

    def set_syntax_error(self, line_number: int | None, message: str) -> None:
        """Mark a syntax-error line in the gutter and attach a tooltip message.

        Args:
            line_number (int | None):
                1-based source line to mark.  ``None`` clears the marker.
            message (str):
                Tooltip text shown for the marked line.
        """
        if line_number is None or line_number < 1 or not message.strip():
            self.clear_syntax_error()
            return
        self._syntax_error_line = line_number
        self._syntax_error_message = message.strip()
        self._line_number_area.update()

    def clear_syntax_error(self) -> None:
        """Clear any syntax-error marker and tooltip from the gutter."""
        self._syntax_error_line = None
        self._syntax_error_message = ""
        self._line_number_area.setToolTip("")
        self._line_number_area.update()
