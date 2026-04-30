"""Custom SI-aware spin-box widget.

Provides :class:`SISpinBox`, a thin subclass of :class:`pyqtgraph.SpinBox`
that relaxes the suffix-validation rule so that the unit string is appended
automatically when the user omits it.
"""

from __future__ import annotations

import pyqtgraph as pg

__all__ = ["SISpinBox"]


class SISpinBox(pg.SpinBox):
    """A :class:`pyqtgraph.SpinBox` subclass with relaxed suffix validation.

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

    Examples:
        >>> from stoner_measurement.ui.widgets import SISpinBox
        >>> spin = SISpinBox(suffix='K', siPrefix=True, value=100.0)
        >>> spin.setOpts(value=200.0)
        >>> spin.value()
        200.0
    """

    def interpret(self) -> float | int | bool:
        """Return the value represented by the current text, or ``False``.

        Extends the base implementation to automatically append the configured
        suffix when the user omits it, so that plain numeric input (or input
        containing only an SI prefix) is accepted without requiring the user to
        type the unit string.

        Returns:
            (float | int): The parsed value when the text is valid.
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

        suffix = self.opts.get("suffix", "")
        if not suffix:
            return False

        le = self.lineEdit()
        original_text = le.text()

        # Strip the configured prefix and whitespace to get the user's raw input.
        user_input = original_text.removeprefix(self.opts["prefix"]).strip()

        # If the text already ends with the suffix the parent failed for an
        # unrelated reason (e.g. bad number format), so don't retry.
        if user_input.endswith(suffix):
            return False

        # Temporarily set the text to a normalised form that includes the
        # suffix, and let the parent parse it — this ensures all base-class
        # parsing rules are respected without duplicating internal logic.
        # We reconstruct from the normalised prefix + user_input to avoid any
        # trailing whitespace artefacts in the original text.
        self.skipValidate = True
        try:
            le.setText(self.opts["prefix"] + user_input + suffix)
            result = super().interpret()
        finally:
            le.setText(original_text)
            self.skipValidate = False

        return result
