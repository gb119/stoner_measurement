"""GUI-thread reclamation of managed widget Python cycles."""

import gc
from threading import get_ident
from weakref import ref

import pytest
from qtpy.QtWidgets import QWidget


def test_managed_widget_reclaims_cycles_before_next_worker(request, qapp):
    gui_thread = get_ident()
    finalized = []
    was_enabled = gc.isenabled()
    gc.disable()

    def verify_teardown():
        try:
            assert widget_ref() is None
            assert finalized == [gui_thread]
            assert not gc.isenabled()
        finally:
            if was_enabled:
                gc.enable()

    # Register first so this assertion runs after managed widget teardown.
    request.addfinalizer(verify_teardown)
    manage = request.getfixturevalue("managed_qt_widget")

    class CyclicWidget(QWidget):
        def __init__(self):
            super().__init__()
            self.cycle = self

        def __del__(self):
            finalized.append(get_ident())

    widget = manage(CyclicWidget())
    widget_ref = ref(widget)
    del widget
    assert widget_ref() is not None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
