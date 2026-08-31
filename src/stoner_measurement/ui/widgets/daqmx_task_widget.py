"""NI-DAQmx device, channel, and saved-task discovery widget."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from qtpy.QtCore import Qt  # type: ignore[attr-defined]
from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.qt_compat import pyqtSignal


class DaqmxTaskKind(StrEnum):
    """Direction of the DAQmx task being defined."""

    ACQUISITION = "acquisition"
    OUTPUT = "output"


class DaqmxSelectionMode(StrEnum):
    """Source used to define a DAQmx task."""

    PHYSICAL_CHANNELS = "physical_channels"
    GLOBAL_CHANNELS = "global_channels"
    SAVED_TASK = "saved_task"


@dataclass(frozen=True)
class DaqmxNamedResource:
    """Named MAX resource and its discovered task direction, if known."""

    name: str
    task_kind: DaqmxTaskKind | None = None


@dataclass(frozen=True)
class DaqmxDeviceInfo:
    """Physical channels and routing terminals discovered for one device."""

    name: str
    product_type: str = ""
    analog_inputs: tuple[str, ...] = ()
    analog_outputs: tuple[str, ...] = ()
    digital_inputs: tuple[str, ...] = ()
    digital_outputs: tuple[str, ...] = ()
    counter_inputs: tuple[str, ...] = ()
    counter_outputs: tuple[str, ...] = ()
    terminals: tuple[str, ...] = ()

    def channel_groups(self, task_kind: DaqmxTaskKind) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Return labelled channel groups compatible with *task_kind*."""
        if task_kind is DaqmxTaskKind.ACQUISITION:
            return (
                ("Analog input", self.analog_inputs),
                ("Digital input", self.digital_inputs),
                ("Counter input", self.counter_inputs),
            )
        return (
            ("Analog output", self.analog_outputs),
            ("Digital output", self.digital_outputs),
            ("Counter output", self.counter_outputs),
        )


@dataclass(frozen=True)
class DaqmxSystemInfo:
    """Immutable snapshot of the locally configured DAQmx system."""

    devices: tuple[DaqmxDeviceInfo, ...] = ()
    scales: tuple[str, ...] = ()
    global_channels: tuple[DaqmxNamedResource, ...] = ()
    saved_tasks: tuple[DaqmxNamedResource, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DaqmxTaskDefinition:
    """Serializable selection returned by :class:`DaqmxTaskDefinitionWidget`."""

    task_kind: DaqmxTaskKind = DaqmxTaskKind.ACQUISITION
    selection_mode: DaqmxSelectionMode = DaqmxSelectionMode.PHYSICAL_CHANNELS
    device: str = ""
    physical_channels: tuple[str, ...] = ()
    custom_scale: str = ""
    global_channels: tuple[str, ...] = ()
    saved_task: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        result = asdict(self)
        result["task_kind"] = self.task_kind.value
        result["selection_mode"] = self.selection_mode.value
        result["physical_channels"] = list(self.physical_channels)
        result["global_channels"] = list(self.global_channels)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> DaqmxTaskDefinition:
        """Build a definition from a JSON-compatible mapping."""
        physical_channels = value.get("physical_channels", ())
        global_channels = value.get("global_channels", ())
        return cls(
            task_kind=DaqmxTaskKind(str(value.get("task_kind", DaqmxTaskKind.ACQUISITION))),
            selection_mode=DaqmxSelectionMode(
                str(value.get("selection_mode", DaqmxSelectionMode.PHYSICAL_CHANNELS))
            ),
            device=str(value.get("device", "")),
            physical_channels=_string_tuple(physical_channels),
            custom_scale=str(value.get("custom_scale", "")),
            global_channels=_string_tuple(global_channels),
            saved_task=str(value.get("saved_task", "")),
        )


class DaqmxDiscoveryError(RuntimeError):
    """Raised when the NI Python package or local DAQmx system is unavailable."""


def _string_tuple(value: object) -> tuple[str, ...]:
    """Coerce a serialized sequence to strings without splitting scalar text."""
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _names(collection: Any, attribute: str = "channel_names") -> tuple[str, ...]:
    """Return a sorted tuple from a nidaqmx collection name property."""
    return tuple(sorted(str(name) for name in getattr(collection, attribute)))


def _task_kind_from_channel_type(channel_type: object) -> DaqmxTaskKind | None:
    """Map a nidaqmx ``ChannelType`` value to acquisition or output."""
    name = getattr(channel_type, "name", str(channel_type)).upper()
    if name in {"ANALOG_INPUT", "DIGITAL_INPUT", "COUNTER_INPUT"}:
        return DaqmxTaskKind.ACQUISITION
    if name in {"ANALOG_OUTPUT", "DIGITAL_OUTPUT", "COUNTER_OUTPUT"}:
        return DaqmxTaskKind.OUTPUT
    return None


def _combined_names(*collections: Any) -> tuple[str, ...]:
    """Return sorted unique channel names from related DAQmx collections."""
    return tuple(sorted({name for collection in collections for name in _names(collection)}))


def _discover_from_system(
    system: Any,
    task_factory: Callable[[], Any],
) -> DaqmxSystemInfo:
    """Build a discovery snapshot from a nidaqmx-compatible system object."""
    warnings: list[str] = []
    devices: list[DaqmxDeviceInfo] = []
    device_collection = getattr(system, "devices")
    for device_name in _names(device_collection, "device_names"):
        try:
            device = device_collection[device_name]
            devices.append(
                DaqmxDeviceInfo(
                    name=device_name,
                    product_type=str(getattr(device, "product_type", "")),
                    analog_inputs=_names(device.ai_physical_chans),
                    analog_outputs=_names(device.ao_physical_chans),
                    digital_inputs=_combined_names(device.di_lines, device.di_ports),
                    digital_outputs=_combined_names(device.do_lines, device.do_ports),
                    counter_inputs=_names(device.ci_physical_chans),
                    counter_outputs=_names(device.co_physical_chans),
                    terminals=tuple(sorted(str(name) for name in getattr(device, "terminals", ()))),
                )
            )
        except Exception as exc:  # nidaqmx exposes driver-specific exception subclasses
            warnings.append(f"Could not inspect DAQmx device {device_name!r}: {exc}")

    global_channels: list[DaqmxNamedResource] = []
    for channel_name in _names(getattr(system, "global_channels"), "global_channel_names"):
        task_kind = None
        try:
            with task_factory() as task:
                task.add_global_channels([system.global_channels[channel_name]])
                task_kind = _task_kind_from_channel_type(task.channels.chan_type)
        except Exception as exc:
            warnings.append(f"Could not inspect DAQmx global channel {channel_name!r}: {exc}")
        global_channels.append(DaqmxNamedResource(channel_name, task_kind))

    saved_tasks: list[DaqmxNamedResource] = []
    for task_name in _names(getattr(system, "tasks"), "task_names"):
        task_kind = None
        task = None
        try:
            task = system.tasks[task_name].load()
            task_kind = _task_kind_from_channel_type(task.channels.chan_type)
        except Exception as exc:
            warnings.append(f"Could not inspect DAQmx saved task {task_name!r}: {exc}")
        finally:
            if task is not None:
                task.close()
        saved_tasks.append(DaqmxNamedResource(task_name, task_kind))

    return DaqmxSystemInfo(
        devices=tuple(devices),
        scales=_names(getattr(system, "scales"), "scale_names"),
        global_channels=tuple(global_channels),
        saved_tasks=tuple(saved_tasks),
        warnings=tuple(warnings),
    )


def discover_daqmx_system() -> DaqmxSystemInfo:
    """Discover devices and MAX-persisted resources using NI's ``nidaqmx`` package."""
    try:
        import nidaqmx  # type: ignore[import-not-found]
        import nidaqmx.system  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        raise DaqmxDiscoveryError(
            "NI-DAQmx discovery requires the optional 'nidaqmx' package and NI-DAQmx driver."
        ) from exc

    try:
        return _discover_from_system(nidaqmx.system.System.local(), nidaqmx.Task)
    except Exception as exc:  # translate the NI driver boundary into a stable UI-facing error
        raise DaqmxDiscoveryError(f"Could not query the local NI-DAQmx system: {exc}") from exc


class DaqmxTaskDefinitionWidget(QWidget):
    """Select physical channels, MAX global channels, or a saved DAQmx task."""

    definition_changed = pyqtSignal(object)
    refresh_requested = pyqtSignal()
    discovery_failed = pyqtSignal(str)
    snapshot_changed = pyqtSignal(object)

    _MODE_LABELS = {
        DaqmxSelectionMode.PHYSICAL_CHANNELS: "Physical channels",
        DaqmxSelectionMode.GLOBAL_CHANNELS: "MAX global channels",
        DaqmxSelectionMode.SAVED_TASK: "MAX saved task",
    }

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        task_kind: DaqmxTaskKind = DaqmxTaskKind.ACQUISITION,
        discovery_provider: Callable[[], DaqmxSystemInfo] = discover_daqmx_system,
        auto_refresh: bool = False,
    ) -> None:
        super().__init__(parent)
        self._task_kind = task_kind
        self._discovery_provider = discovery_provider
        self._snapshot = DaqmxSystemInfo()
        self._updating = False
        self._visible_channel_rows = 4 if task_kind is DaqmxTaskKind.ACQUISITION else 1
        self._build_ui()
        if auto_refresh:
            self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QFormLayout()
        mode_row = QWidget(self)
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.selection_mode_combo = QComboBox(mode_row)
        for mode, label in self._MODE_LABELS.items():
            self.selection_mode_combo.addItem(label, mode.value)
        self.refresh_button = QPushButton("Refresh", mode_row)
        mode_layout.addWidget(self.selection_mode_combo, 1)
        mode_layout.addWidget(self.refresh_button)
        header.addRow("Define from", mode_row)
        layout.addLayout(header)

        self.pages = QStackedWidget(self)
        self.pages.addWidget(self._build_physical_page())
        self.pages.addWidget(self._build_global_page())
        self.pages.addWidget(self._build_saved_task_page())
        layout.addWidget(self.pages)

        self.status_label = QLabel("Select Refresh to discover NI-DAQmx resources.", self)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.activate()
        self.setFixedHeight(self.sizeHint().height())

        self.selection_mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.scale_combo.currentTextChanged.connect(self._emit_definition_changed)
        self.physical_tree.itemChanged.connect(self._emit_definition_changed)
        self.global_channel_list.itemChanged.connect(self._emit_definition_changed)
        self.saved_task_combo.currentTextChanged.connect(self._emit_definition_changed)
        self.refresh_button.clicked.connect(self.refresh)

    def _build_physical_page(self) -> QWidget:
        page = QWidget(self)
        layout = QFormLayout(page)
        self.device_combo = QComboBox(page)
        layout.addRow("Device", self.device_combo)
        self.physical_tree = QTreeWidget(page)
        self.physical_tree.setHeaderLabels(["Physical channel"])
        tree_row_height = self.physical_tree.fontMetrics().height() + 8
        tree_height = (
            self.physical_tree.header().sizeHint().height()
            + (self._visible_channel_rows + 1) * tree_row_height
            + 2 * self.physical_tree.frameWidth()
        )
        self.physical_tree.setFixedHeight(tree_height)
        layout.addRow("Channels", self.physical_tree)
        self.scale_combo = QComboBox(page)
        self.scale_combo.addItem("(No custom scale)", "")
        layout.addRow("Custom scale (analog)", self.scale_combo)
        return page

    def _build_global_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.global_channel_list = QListWidget(page)
        list_row_height = self.global_channel_list.fontMetrics().height() + 8
        self.global_channel_list.setFixedHeight(
            self._visible_channel_rows * list_row_height + 2 * self.global_channel_list.frameWidth()
        )
        layout.addWidget(self.global_channel_list)
        return page

    def _build_saved_task_page(self) -> QWidget:
        page = QWidget(self)
        layout = QFormLayout(page)
        self.saved_task_combo = QComboBox(page)
        layout.addRow("Saved task", self.saved_task_combo)
        return page

    @property
    def snapshot(self) -> DaqmxSystemInfo:
        """Return the latest discovery snapshot."""
        return self._snapshot

    def task_kind(self) -> DaqmxTaskKind:
        """Return the programmatically fixed acquisition/output direction."""
        return self._task_kind

    def selection_mode(self) -> DaqmxSelectionMode:
        """Return the selected source mode."""
        return DaqmxSelectionMode(self.selection_mode_combo.currentData())

    def set_selection_mode(self, mode: DaqmxSelectionMode) -> None:
        """Select physical, global-channel, or saved-task mode."""
        self.selection_mode_combo.setCurrentIndex(self.selection_mode_combo.findData(mode.value))

    def refresh(self) -> None:
        """Refresh all DAQmx resources while preserving the current definition."""
        previous = self.definition()
        self.refresh_requested.emit()
        try:
            snapshot = self._discovery_provider()
        except DaqmxDiscoveryError as exc:
            message = str(exc)
            self.status_label.setText(message)
            self.discovery_failed.emit(message)
            return
        self.set_snapshot(snapshot, preserve=previous)

    def set_snapshot(
        self,
        snapshot: DaqmxSystemInfo,
        *,
        preserve: DaqmxTaskDefinition | None = None,
    ) -> None:
        """Install a discovery snapshot, optionally restoring a definition."""
        self._snapshot = snapshot
        self._updating = True
        try:
            self.device_combo.clear()
            for device in snapshot.devices:
                label = (
                    f"{device.name} — {device.product_type}" if device.product_type else device.name
                )
                self.device_combo.addItem(label, device.name)
            self.scale_combo.clear()
            self.scale_combo.addItem("(No custom scale)", "")
            for scale in snapshot.scales:
                self.scale_combo.addItem(scale, scale)
            self._populate_for_task_kind()
            if preserve is not None:
                self.set_definition(preserve)
        finally:
            self._updating = False
        if snapshot.warnings:
            self.status_label.setText(
                f"Discovered resources with {len(snapshot.warnings)} warning(s): "
                + snapshot.warnings[0]
            )
        else:
            self.status_label.setText(
                f"Discovered {len(snapshot.devices)} device(s), "
                f"{len(snapshot.global_channels)} global channel(s), and "
                f"{len(snapshot.saved_tasks)} saved task(s)."
            )
        self._emit_definition_changed()
        self.snapshot_changed.emit(snapshot)

    def definition(self) -> DaqmxTaskDefinition:
        """Return the complete current task selection."""
        return DaqmxTaskDefinition(
            task_kind=self.task_kind(),
            selection_mode=self.selection_mode(),
            device=str(self.device_combo.currentData() or ""),
            physical_channels=tuple(self._checked_tree_values()),
            custom_scale=str(self.scale_combo.currentData() or ""),
            global_channels=tuple(self._checked_list_values()),
            saved_task=str(self.saved_task_combo.currentData() or ""),
        )

    def set_definition(self, definition: DaqmxTaskDefinition) -> None:
        """Restore a previously serialized task selection."""
        if definition.task_kind is not self._task_kind:
            raise ValueError(
                f"Cannot restore a {definition.task_kind.value} definition into "
                f"a {self._task_kind.value} DAQmx widget."
            )
        was_updating = self._updating
        self._updating = True
        try:
            self.set_selection_mode(definition.selection_mode)
            self._select_combo_data(self.device_combo, definition.device)
            self._populate_physical_channels(extra=definition.physical_channels)
            self._set_checked_tree_values(definition.physical_channels)
            self._select_combo_data(self.scale_combo, definition.custom_scale, add_missing=True)
            self._populate_named_resources(
                self.global_channel_list,
                self._snapshot.global_channels,
                extra=definition.global_channels,
            )
            self._set_checked_list_values(definition.global_channels)
            self._select_combo_data(self.saved_task_combo, definition.saved_task, add_missing=True)
        finally:
            self._updating = was_updating
        self._emit_definition_changed()

    def _on_mode_changed(self) -> None:
        self.pages.setCurrentIndex(self.selection_mode_combo.currentIndex())
        self._emit_definition_changed()

    def _on_device_changed(self) -> None:
        self._populate_physical_channels()
        self._emit_definition_changed()

    def _populate_for_task_kind(self) -> None:
        selected_task = str(self.saved_task_combo.currentData() or "")
        self._populate_physical_channels()
        self._populate_named_resources(self.global_channel_list, self._snapshot.global_channels)
        self.saved_task_combo.clear()
        self.saved_task_combo.addItem("(No saved task selected)", "")
        for resource in self._compatible_resources(self._snapshot.saved_tasks):
            self.saved_task_combo.addItem(resource.name, resource.name)
        self._select_combo_data(self.saved_task_combo, selected_task)

    def _populate_physical_channels(self, *, extra: Iterable[str] = ()) -> None:
        previous = set(self._checked_tree_values())
        configured = set(extra)
        selected = previous | configured
        self.physical_tree.blockSignals(True)
        self.physical_tree.clear()
        device_name = str(self.device_combo.currentData() or "")
        device = next((item for item in self._snapshot.devices if item.name == device_name), None)
        known: set[str] = set()
        if device is not None:
            for group_label, channels in device.channel_groups(self.task_kind()):
                if not channels:
                    continue
                group = QTreeWidgetItem([group_label])
                self.physical_tree.addTopLevelItem(group)
                for channel in channels:
                    known.add(channel)
                    child = QTreeWidgetItem([channel])
                    child.setData(0, Qt.ItemDataRole.UserRole, channel)
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    child.setCheckState(
                        0,
                        Qt.CheckState.Checked if channel in selected else Qt.CheckState.Unchecked,
                    )
                    group.addChild(child)
                group.setExpanded(True)
        missing = sorted(configured - known)
        if missing:
            group = QTreeWidgetItem(["Configured but not discovered"])
            self.physical_tree.addTopLevelItem(group)
            for channel in missing:
                child = QTreeWidgetItem([channel])
                child.setData(0, Qt.ItemDataRole.UserRole, channel)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                group.addChild(child)
            group.setExpanded(True)
        self.physical_tree.blockSignals(False)

    def _populate_named_resources(
        self,
        widget: QListWidget,
        resources: Iterable[DaqmxNamedResource],
        *,
        extra: Iterable[str] = (),
    ) -> None:
        previous = set(self._checked_list_values())
        configured = set(extra)
        widget.blockSignals(True)
        widget.clear()
        names = {resource.name for resource in self._compatible_resources(resources)}
        selected = (previous & names) | configured
        names.update(configured)
        for name in sorted(names):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if name in selected else Qt.CheckState.Unchecked
            )
            widget.addItem(item)
        widget.blockSignals(False)

    def _compatible_resources(
        self, resources: Iterable[DaqmxNamedResource]
    ) -> tuple[DaqmxNamedResource, ...]:
        kind = self.task_kind()
        return tuple(resource for resource in resources if resource.task_kind in {None, kind})

    def _checked_tree_values(self) -> list[str]:
        values: list[str] = []
        for group_index in range(self.physical_tree.topLevelItemCount()):
            group = self.physical_tree.topLevelItem(group_index)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child.checkState(0) == Qt.CheckState.Checked:
                    values.append(str(child.data(0, Qt.ItemDataRole.UserRole)))
        return values

    def _set_checked_tree_values(self, values: Iterable[str]) -> None:
        selected = set(values)
        for group_index in range(self.physical_tree.topLevelItemCount()):
            group = self.physical_tree.topLevelItem(group_index)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                child.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if child.data(0, Qt.ItemDataRole.UserRole) in selected
                    else Qt.CheckState.Unchecked,
                )

    def _checked_list_values(self) -> list[str]:
        return [
            str(self.global_channel_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.global_channel_list.count())
            if self.global_channel_list.item(index).checkState() == Qt.CheckState.Checked
        ]

    def _set_checked_list_values(self, values: Iterable[str]) -> None:
        selected = set(values)
        for index in range(self.global_channel_list.count()):
            item = self.global_channel_list.item(index)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.data(Qt.ItemDataRole.UserRole) in selected
                else Qt.CheckState.Unchecked
            )

    @staticmethod
    def _select_combo_data(combo: QComboBox, value: str, *, add_missing: bool = False) -> None:
        index = combo.findData(value)
        if index < 0 and add_missing and value:
            combo.addItem(value, value)
            index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _emit_definition_changed(self) -> None:
        if not self._updating:
            self.definition_changed.emit(self.definition())


__all__ = [
    "DaqmxDeviceInfo",
    "DaqmxDiscoveryError",
    "DaqmxNamedResource",
    "DaqmxSelectionMode",
    "DaqmxSystemInfo",
    "DaqmxTaskDefinition",
    "DaqmxTaskDefinitionWidget",
    "DaqmxTaskKind",
    "discover_daqmx_system",
]
