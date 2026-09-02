"""Tests for exchanging sequence steps through the system clipboard."""

import json

import pytest

from stoner_measurement.core.serializer import sequence_to_json
from stoner_measurement.plugins.trace import DummyPlugin
from stoner_measurement.ui.dock_panel import DockPanel


@pytest.fixture
def panel(plugin_manager, managed_qt_widget, monkeypatch, qapp):
    """Return an isolated dock panel and clear the shared clipboard."""
    monkeypatch.setattr(
        "stoner_measurement.ui.dock_panel.load_plugin_catalogue_config",
        lambda: {"items": []},
    )
    clipboard = qapp.clipboard()
    clipboard.clear()
    yield managed_qt_widget(DockPanel(plugin_manager=plugin_manager))
    clipboard.clear()


def test_copy_publishes_sequence_json_as_plain_text_and_json(panel, qapp):
    """Copied steps can be pasted into arbitrary text applications."""
    plugin = DummyPlugin()
    plugin.instance_name = "copied_dummy"
    panel.load_sequence([plugin])
    item = panel._sequence_tree.topLevelItem(0)  # noqa: SLF001
    panel._sequence_tree.setCurrentItem(item)  # noqa: SLF001
    item.setSelected(True)

    assert panel.copy_selected_step()

    mime_data = qapp.clipboard().mimeData()
    assert mime_data.hasText()
    assert mime_data.hasFormat("application/json")
    payload = json.loads(mime_data.text())
    assert payload["steps"][0]["plugin"]["instance_name"] == "copied_dummy"


def test_paste_accepts_valid_plain_text_sequence_json(panel, qapp):
    """Canonical sequence JSON from another application can be pasted back."""
    plugin = DummyPlugin()
    plugin.instance_name = "external_dummy"
    qapp.clipboard().setText(json.dumps(sequence_to_json([plugin])))

    assert panel.has_clipboard_step
    assert panel.paste_step()
    assert panel.sequence_steps[0].instance_name == "external_dummy"


def test_unrelated_system_text_does_not_paste_stale_internal_step(panel, qapp):
    """Non-sequence text replaces rather than exposes an earlier copied step."""
    panel.load_sequence([DummyPlugin()])
    item = panel._sequence_tree.topLevelItem(0)  # noqa: SLF001
    panel._sequence_tree.setCurrentItem(item)  # noqa: SLF001
    item.setSelected(True)
    assert panel.copy_selected_step()

    qapp.clipboard().setText("ordinary text from another application")

    assert not panel.has_clipboard_step
    assert not panel.paste_step()
    assert len(panel.sequence_steps) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
