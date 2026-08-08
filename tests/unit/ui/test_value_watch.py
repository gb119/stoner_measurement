"""Value-watch window behaviour."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.ui.value_watch import ValueWatchWindow


def test_selected_catalogue_value_is_displayed_and_updated(
    qapp,
    engine,
    managed_qt_widget,
):
    """Selecting an available value creates a live readout in the grid."""
    plugin = CounterPlugin()
    plugin.value = 12.5
    engine._namespace[plugin.instance_name] = plugin  # noqa: SLF001
    engine.update_step_plugin_catalog([plugin])
    key = "counter:Value"
    window = managed_qt_widget(ValueWatchWindow(engine))

    window.show()
    window._btn_config.click()  # noqa: SLF001
    qapp.processEvents()

    checkbox = window._selector._checkboxes[key]  # noqa: SLF001
    checkbox.setChecked(True)
    qapp.processEvents()

    display = window._displays[key]  # noqa: SLF001
    assert window._display_layout.indexOf(display) >= 0  # noqa: SLF001
    assert display._value_label.text() == "12.5"  # noqa: SLF001

    plugin.value = 18.75
    engine.notify_namespace_updated()
    qapp.processEvents()

    assert display._value_label.text() == "18.75"  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
