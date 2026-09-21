"""Shared temperature reference selectors and plugin compatibility helpers."""

from qtpy.QtWidgets import QComboBox

from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.temperature_control.references import (
    ChannelRef,
    LoopRef,
    channel_ref,
    loop_ref,
)


def selected_session(slot):
    """Resolve a plugin's controller, retaining the original primary API."""
    engine = TemperatureControllerEngine.instance()
    return engine if slot == "primary" else engine.controller(slot)


def local_loop_value(state, name, value, default=None):
    """Read a loop value from its owner's snapshot."""
    ref = loop_ref(value)
    local = state if ref.controller_id == "primary" else state.for_controller(ref.controller_id)
    return getattr(local, name).get(ref.loop, default)


def sensor_reading(state, value):
    """Read a sensor without falling back to another controller."""
    ref = channel_ref(value)
    local = state if ref.controller_id == "primary" else state.for_controller(ref.controller_id)
    return local.readings.get(ref.channel)


def compact_reference(value):
    """Keep legacy labels and script arguments for primary selections."""
    if value.controller_id == "primary":
        return value.loop if isinstance(value, LoopRef) else value.channel
    return value


def selection_text(value):
    """Format editable selection text using stable IDs, not display labels."""
    if isinstance(value, (LoopRef, ChannelRef)):
        local = value.loop if isinstance(value, LoopRef) else value.channel
        return str(local) if value.controller_id == "primary" else f"secondary:{local}"
    return str(value)


def parse_selection(text, *, loops=False):
    """Parse qualified selection text; unqualified entries mean primary."""
    values = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        slot = "primary"
        if item.startswith(("primary:", "secondary:")):
            slot, item = item.split(":", 1)
        ref = LoopRef(slot, int(item)) if loops else ChannelRef(slot, item)
        value = compact_reference(ref)
        if value not in values:
            values.append(value)
    return values


class TemperatureLoopSelector(QComboBox):
    """Select an advertised owned loop, preserving unavailable saved targets."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.setObjectName("control_loop")
        self._plugin = plugin
        self._engine = TemperatureControllerEngine.instance()
        self.refresh()
        self.currentIndexChanged.connect(self._selected)
        publisher = getattr(self._engine, "publisher", None)
        if publisher is not None:
            publisher.connection_changed.connect(self.refresh)

    def refresh(self):
        """Refresh topology while retaining the stored reference."""
        selected = LoopRef(self._plugin.controller_id, self._plugin.control_loop)
        self.blockSignals(True)
        self.clear()
        catalogue = getattr(self._engine, "loop_catalogue", lambda: [])()
        for descriptor in catalogue:
            self.addItem(descriptor.label, descriptor.reference)
        index = next((i for i in range(self.count()) if self.itemData(i) == selected), -1)
        if index < 0:
            self.addItem(f"{selected} (unavailable)", selected)
            index = self.count() - 1
        self.setCurrentIndex(index)
        self.blockSignals(False)

    def _selected(self, index):
        ref = self.itemData(index)
        if ref is not None:
            self._plugin.controller_id = ref.controller_id
            self._plugin.control_loop = ref.loop
            refresh = getattr(self._plugin, "_refresh_catalogs", None)
            if refresh:
                refresh()


class TemperatureCataloguePicker(QComboBox):
    """Append an advertised reference to an editable multi-selection list."""

    def __init__(self, editor, *, loops=False):
        super().__init__(editor.parentWidget())
        self._editor = editor
        self._loops = loops
        self._engine = TemperatureControllerEngine.instance()
        self.refresh()
        self.currentIndexChanged.connect(self._selected)
        publisher = getattr(self._engine, "publisher", None)
        if publisher is not None:
            publisher.connection_changed.connect(self.refresh)

    def refresh(self):
        """Update options when an owned connection changes."""
        self.blockSignals(True)
        self.clear()
        self.addItem("Add a loop…" if self._loops else "Add a sensor…", None)
        method = "loop_catalogue" if self._loops else "channel_catalogue"
        for descriptor in getattr(self._engine, method, lambda: [])():
            self.addItem(descriptor.label, descriptor.reference)
        self.blockSignals(False)

    def _selected(self, index):
        ref = self.itemData(index)
        if ref is None:
            return
        text = self._editor.text().strip()
        self._editor.setText(f"{text}, {selection_text(ref)}" if text else selection_text(ref))
        self._editor.editingFinished.emit()
        self.setCurrentIndex(0)


def add_catalogue_picker(layout, editor, *, loops=False):
    """Append advertised references to a multi-selection text field."""
    picker = TemperatureCataloguePicker(editor, loops=loops)
    layout.addRow("Available:", picker)
    return picker
