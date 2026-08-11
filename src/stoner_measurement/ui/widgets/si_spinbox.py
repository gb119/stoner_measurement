"""Custom SI-aware spin-box widget.

Provides :class:`SISpinBox`, a thin subclass of :class:`pyqtgraph.SpinBox`
that accepts either SI-aware numeric values or expressions which can be stored
and evaluated later in the sequence-engine namespace.
"""

# pyqtgraph's public override API uses camelCase names.
# pylint: disable=invalid-name

from __future__ import annotations

import pyqtgraph as pg

__all__ = ["SISpinBox"]


class SISpinBox(pg.SpinBox):
    """An SI-aware spin box which can retain a runtime expression.

    The standard :class:`~pyqtgraph.SpinBox` requires the user to include the
    configured unit suffix when editing a value by hand (e.g. the field must
    contain ``"200 K"`` rather than just ``"200"``).  This subclass overrides
    :meth:`interpret` so that the suffix is appended automatically when absent,
    making editing more convenient without removing any existing functionality.

    The extended behaviour covers three cases:

    * **No suffix typed** — the spin box suffix is appended before parsing.
      ``"200"`` → ``"200 K"`` → value ``200 K``.
    * **SI prefix typed without suffix** — the suffix is appended after the
      SI prefix.  ``"200m"`` → ``"200mK"`` → value ``0.2 K`` (200 mK).
    * **Full string typed** — the existing pyqtgraph behaviour is used
      unchanged.  ``"200 mK"`` → value ``0.2 K``.

    All constructor arguments are forwarded unchanged to
    :class:`~pyqtgraph.SpinBox`.

    A non-empty string which is not a valid number is retained as a runtime
    expression.  In expression mode :meth:`value` returns that string;
    otherwise it retains the standard pyqtgraph numeric return type.  The
    widget deliberately does not evaluate expressions itself because it does
    not own the sequence-engine namespace.  Plugins should store the returned
    value and resolve it during execution, for example with
    ``self.eval_float(setting)``.

    Examples:
        >>> from stoner_measurement.ui.widgets import SISpinBox
        >>> spin = SISpinBox(suffix='K', siPrefix=True, value=100.0)
        >>> spin.setOpts(value=200.0)
        >>> spin.value()
        200.0

    Notes:
        The base :class:`pyqtgraph.SpinBox` can render a little tightly with
        the application's default font metrics, especially in dark mode. This
        subclass therefore also applies a slightly larger minimum height so the
        text and suffix remain fully visible and appear better centred
        vertically.
    """

    def __init__(self, *args, allow_expressions: bool = False, **kwargs) -> None:
        """Initialise the SI-aware spin box.

        Keyword Parameters:
            allow_expressions (bool):
                Retain non-numeric text for runtime evaluation.  This is
                opt-in because direct hardware-control panels do not have a
                sequence-engine namespace in which to resolve expressions.
        """
        self._allow_expressions = bool(allow_expressions)
        self._expression: str | None = None

        # pyqtgraph converts the initial value directly to Decimal before it
        # calls setValue(), so give it a numeric placeholder and install a
        # requested expression after base initialisation.
        initial_expression: str | None = None
        if self._allow_expressions and isinstance(kwargs.get("value"), str):
            initial_expression = kwargs["value"]
            try:
                kwargs["value"] = float(initial_expression)
            except ValueError:
                kwargs["value"] = 0.0
        elif self._allow_expressions and len(args) > 1 and isinstance(args[1], str):
            initial_expression = args[1]
            try:
                numeric_fallback = float(initial_expression)
            except ValueError:
                numeric_fallback = 0.0
            args = (*args[:1], numeric_fallback, *args[2:])

        super().__init__(*args, **kwargs)
        if initial_expression is not None:
            self.setValue(initial_expression)
        minimum_height = max(self.minimumHeight(), 28)
        self.setMinimumHeight(minimum_height)
        line_edit = self.lineEdit()
        line_edit.setMinimumHeight(max(line_edit.minimumHeight(), minimum_height - 4))

    def value(self) -> float | int | str:
        """Return the numeric value or the retained runtime expression."""
        if self._expression is not None:
            return self._expression
        return super().value()

    def setValue(self, value=None, update=True, delaySignal=False):  # noqa: N802
        """Set a numeric value or retain a string for runtime evaluation."""
        if self._allow_expressions and isinstance(value, str):
            expression = value.strip()
            if not expression:
                return self.value()
            changed = expression != self._expression
            self._expression = expression
            if update:
                self.updateText()
            if changed:
                self.sigValueChanging.emit(self, expression)
                if not delaySignal:
                    self.emitChanged()
            return expression

        if value is None and self._expression is not None:
            if update:
                self.updateText()
            return self._expression

        was_expression = self._expression is not None
        previous_numeric = self.val
        self._expression = None
        result = super().setValue(value, update=update, delaySignal=delaySignal)
        if was_expression and self.val == previous_numeric:
            numeric_value = super().value()
            self.sigValueChanging.emit(self, numeric_value)
            if not delaySignal:
                self.emitChanged()
        return result

    def emitChanged(self) -> None:
        """Emit the current expression or delegate numeric signal handling."""
        if self._expression is None:
            super().emitChanged()
            return
        self.lastValEmitted = self._expression
        self.valueChanged.emit(self._expression)
        self.sigValueChanged.emit(self)

    def delayedChange(self) -> None:  # noqa: N802 - pyqtgraph callback name
        """Coalesce delayed expression changes using the expression value."""
        if self._expression is None:
            super().delayedChange()
        elif self._expression != self.lastValEmitted:
            self.emitChanged()

    def updateText(self) -> None:  # noqa: N802 - pyqtgraph override name
        """Display an expression verbatim, or format the numeric value."""
        if self._expression is None:
            super().updateText()
            return
        self.skipValidate = True
        try:
            self.lineEdit().setText(self._expression)
            self.lastText = self._expression
        finally:
            self.skipValidate = False

    def valueInRange(self, value) -> bool:  # noqa: N802 - pyqtgraph override name
        """Expressions are valid pending evaluation in the engine namespace."""
        if isinstance(value, str):
            return bool(value.strip())
        return super().valueInRange(value)

    def interpret(self) -> float | int | str | bool:
        """Return the value represented by the current text, or ``False``.

        Extends the base implementation to automatically append the configured
        suffix when the user omits it, so that plain numeric input (or input
        containing only an SI prefix) is accepted without requiring the user to
        type the unit string.

        Returns:
            (float | int): The parsed value when the text is valid.
            (str): A non-empty expression to evaluate at sequence runtime.
            (bool): ``False`` when the text cannot be parsed.

        Examples:
            >>> spin = SISpinBox(suffix='K', siPrefix=True)
            >>> spin.lineEdit().setText('200')
            >>> spin.interpret() == 200.0
            True
            >>> spin.lineEdit().setText('200m')
            >>> abs(spin.interpret() - 0.2) < 1e-9
            True
        """
        result = super().interpret()
        if result is not False:
            return result

        le = self.lineEdit()
        original_text = le.text()

        suffix = self.opts.get("suffix", "")
        if not suffix:
            return (original_text.strip() or False) if self._allow_expressions else False

        # Strip the configured prefix and whitespace to get the user's raw input.
        user_input = original_text.removeprefix(self.opts["prefix"]).strip()

        # If the text already ends with the suffix the parent failed for an
        # unrelated reason (e.g. bad number format), so don't retry.
        if user_input.endswith(suffix):
            return (original_text.strip() or False) if self._allow_expressions else False

        # Temporarily set the text to a normalised form that includes the
        # suffix, and let the parent parse it — this ensures all base-class
        # parsing rules are respected without duplicating internal logic.
        # We reconstruct from the normalised prefix + user_input to avoid any
        # trailing whitespace artefacts in the original text.
        self.skipValidate = True  # pylint: disable=invalid-name
        try:
            le.setText(self.opts["prefix"] + user_input + suffix)
            result = super().interpret()
        finally:
            le.setText(original_text)
            self.skipValidate = False  # pylint: disable=invalid-name

        if result is not False:
            return result

        return (original_text.strip() or False) if self._allow_expressions else False

    def refresh(self) -> None:
        """Refresh the widget display."""
        self.update()
