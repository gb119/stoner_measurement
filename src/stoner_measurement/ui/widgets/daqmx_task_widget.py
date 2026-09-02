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
from stoner_measurement.ui.widgets.si_combo_box import SIComboBox
from stoner_measurement.ui.widgets.si_spinbox import SISpinBox


class DaqmxTaskKind(StrEnum):
    """Direction of the DAQmx task being defined."""

    ACQUISITION = "acquisition"
    OUTPUT = "output"


class DaqmxChannelFamily(StrEnum):
    """Broad DAQmx channel family exposed by a task selector."""

    ANALOG = "analog"
    DIGITAL = "digital"


class DaqmxTerminalConfiguration(StrEnum):
    """Terminal wiring used for all physical analogue input channels."""

    DEFAULT = "default"
    RSE = "rse"
    NRSE = "nrse"
    DIFFERENTIAL = "differential"


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
    channel_family: DaqmxChannelFamily | None = None


@dataclass(frozen=True)
class DaqmxInputRange:
    """Symmetric measurement range for one physical analogue input channel."""

    channel: str
    range: float = 10.0

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "channel": self.channel,
            "range": self.range,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> DaqmxInputRange:
        """Build a channel range from serialized data."""
        if "range" in value:
            input_range = float(value["range"])
        else:
            input_range = max(
                abs(float(value.get("minimum", -10.0))),
                abs(float(value.get("maximum", 10.0))),
            )
        return cls(channel=str(value.get("channel", "")), range=input_range)


@dataclass(frozen=True)
class DaqmxDeviceInfo:
    """Physical channels and routing terminals discovered for one device."""

    name: str
    product_type: str = ""
    analog_inputs: tuple[str, ...] = ()
    analog_input_ranges: tuple[float, ...] = ()
    analog_outputs: tuple[str, ...] = ()
    digital_inputs: tuple[str, ...] = ()
    digital_outputs: tuple[str, ...] = ()
    counter_inputs: tuple[str, ...] = ()
    counter_outputs: tuple[str, ...] = ()
    terminals: tuple[str, ...] = ()

    def channel_groups(
        self,
        task_kind: DaqmxTaskKind,
        channel_family: DaqmxChannelFamily | None = None,
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Return labelled channel groups compatible with *task_kind*."""
        if task_kind is DaqmxTaskKind.ACQUISITION:
            groups = (
                ("Analog input", self.analog_inputs),
                ("Digital input", self.digital_inputs),
                ("Counter input", self.counter_inputs),
            )
        else:
            groups = (
                ("Analog output", self.analog_outputs),
                ("Digital output", self.digital_outputs),
                ("Counter output", self.counter_outputs),
            )
        if channel_family is None:
            return groups
        index = 0 if channel_family is DaqmxChannelFamily.ANALOG else 1
        return (groups[index],)


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
    terminal_configuration: DaqmxTerminalConfiguration = DaqmxTerminalConfiguration.DEFAULT
    input_ranges: tuple[DaqmxInputRange, ...] = ()
    global_channels: tuple[str, ...] = ()
    saved_task: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        result = asdict(self)
        result["task_kind"] = self.task_kind.value
        result["selection_mode"] = self.selection_mode.value
        result["terminal_configuration"] = self.terminal_configuration.value
        result["input_ranges"] = [input_range.to_dict() for input_range in self.input_ranges]
        result["physical_channels"] = list(self.physical_channels)
        result["global_channels"] = list(self.global_channels)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> DaqmxTaskDefinition:
        """Build a definition from a JSON-compatible mapping."""
        physical_channels = value.get("physical_channels", ())
        global_channels = value.get("global_channels", ())
        input_ranges = value.get("input_ranges", ())
        return cls(
            task_kind=DaqmxTaskKind(str(value.get("task_kind", DaqmxTaskKind.ACQUISITION))),
            selection_mode=DaqmxSelectionMode(
                str(value.get("selection_mode", DaqmxSelectionMode.PHYSICAL_CHANNELS))
            ),
            device=str(value.get("device", "")),
            physical_channels=_string_tuple(physical_channels),
            custom_scale=str(value.get("custom_scale", "")),
            terminal_configuration=DaqmxTerminalConfiguration(
                str(value.get("terminal_configuration", DaqmxTerminalConfiguration.DEFAULT))
            ),
            input_ranges=_input_ranges(input_ranges),
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


def _input_ranges(value: object) -> tuple[DaqmxInputRange, ...]:
    """Coerce serialized per-channel range mappings."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        DaqmxInputRange.from_dict(item) for item in value if isinstance(item, dict)
    )


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


def _channel_family_from_channel_type(channel_type: object) -> DaqmxChannelFamily | None:
    """Map a nidaqmx ``ChannelType`` value to its analogue/digital family."""
    name = getattr(channel_type, "name", str(channel_type)).upper()
    if name in {"ANALOG_INPUT", "ANALOG_OUTPUT"}:
        return DaqmxChannelFamily.ANALOG
    if name in {"DIGITAL_INPUT", "DIGITAL_OUTPUT"}:
        return DaqmxChannelFamily.DIGITAL
    return None


def _combined_names(*collections: Any) -> tuple[str, ...]:
    """Return sorted unique channel names from related DAQmx collections."""
    return tuple(sorted({name for collection in collections for name in _names(collection)}))


def _symmetric_voltage_ranges(values: Iterable[float]) -> tuple[float, ...]:
    """Convert DAQmx low/high range pairs to positive symmetric limits."""
    limits = tuple(float(value) for value in values)
    return tuple(
        sorted(
            {
                max(abs(low), abs(high))
                for low, high in zip(limits[::2], limits[1::2], strict=False)
                if max(abs(low), abs(high)) > 0
            }
        )
    )


def _device_input_ranges(device: Any) -> tuple[float, ...]:
    """Read optional device voltage ranges without preventing channel discovery."""
    try:
        return _symmetric_voltage_ranges(device.ai_voltage_rngs)
    except Exception:  # some DAQmx devices do not expose voltage ranges
        return ()


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
                    analog_input_ranges=_device_input_ranges(device),
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
        channel_family = None
        try:
            with task_factory() as task:
                task.add_global_channels([system.global_channels[channel_name]])
                task_kind = _task_kind_from_channel_type(task.channels.chan_type)
                channel_family = _channel_family_from_channel_type(task.channels.chan_type)
        except Exception as exc:
            warnings.append(f"Could not inspect DAQmx global channel {channel_name!r}: {exc}")
        global_channels.append(DaqmxNamedResource(channel_name, task_kind, channel_family))

    saved_tasks: list[DaqmxNamedResource] = []
    for task_name in _names(getattr(system, "tasks"), "task_names"):
        task_kind = None
        channel_family = None
        task = None
        try:
            task = system.tasks[task_name].load()
            task_kind = _task_kind_from_channel_type(task.channels.chan_type)
            channel_family = _channel_family_from_channel_type(task.channels.chan_type)
        except Exception as exc:
            warnings.append(f"Could not inspect DAQmx saved task {task_name!r}: {exc}")
        finally:
            if task is not None:
                task.close()
        saved_tasks.append(DaqmxNamedResource(task_name, task_kind, channel_family))

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
        channel_family: DaqmxChannelFamily | None = None,
        discovery_provider: Callable[[], DaqmxSystemInfo] = discover_daqmx_system,
        auto_refresh: bool = False,
    ) -> None:
        super().__init__(parent)
        self._task_kind = task_kind
        self._channel_family = channel_family
        self._discovery_provider = discovery_provider
        self._snapshot = DaqmxSystemInfo()
        self._updating = False
        self._range_widgets: dict[str, SIComboBox | SISpinBox] = {}
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
        self.terminal_configuration_combo.currentTextChanged.connect(
            self._emit_definition_changed
        )
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
        headers = ["Physical channel"]
        if self._shows_input_ranges:
            headers.append("Range")
        self.physical_tree.setHeaderLabels(headers)
        tree_row_height = self.physical_tree.fontMetrics().height() + 8
        tree_height = (
            self.physical_tree.header().sizeHint().height()
            + (self._visible_channel_rows + 1) * tree_row_height
            + 2 * self.physical_tree.frameWidth()
        )
        self.physical_tree.setFixedHeight(tree_height)
        if self._shows_input_ranges:
            self.physical_tree.setToolTip(
                "Symmetric input range (±), in volts unless a custom scale is selected."
            )
        layout.addRow("Channels", self.physical_tree)
        self.terminal_configuration_combo = QComboBox(page)
        terminal_options = (
            ("Device default", DaqmxTerminalConfiguration.DEFAULT),
            ("Referenced single-ended (RSE)", DaqmxTerminalConfiguration.RSE),
            ("Non-referenced single-ended (NRSE)", DaqmxTerminalConfiguration.NRSE),
            ("Differential", DaqmxTerminalConfiguration.DIFFERENTIAL),
        )
        for label, configuration in terminal_options:
            self.terminal_configuration_combo.addItem(label, configuration.value)
        self.terminal_configuration_label = QLabel("Input terminal mode", page)
        terminal_configuration_visible = (
            self._task_kind is DaqmxTaskKind.ACQUISITION
            and self._channel_family is DaqmxChannelFamily.ANALOG
        )
        self.terminal_configuration_label.setVisible(terminal_configuration_visible)
        self.terminal_configuration_combo.setVisible(terminal_configuration_visible)
        layout.addRow(self.terminal_configuration_label, self.terminal_configuration_combo)
        self.scale_combo = QComboBox(page)
        self.scale_combo.addItem("(No custom scale)", "")
        self.scale_label = QLabel("Custom scale (analog)", page)
        scale_visible = self._channel_family is not DaqmxChannelFamily.DIGITAL
        self.scale_label.setVisible(scale_visible)
        self.scale_combo.setVisible(scale_visible)
        layout.addRow(self.scale_label, self.scale_combo)
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

    def channel_family(self) -> DaqmxChannelFamily | None:
        """Return the programmatically fixed analogue/digital family filter."""
        return self._channel_family

    @property
    def _shows_input_ranges(self) -> bool:
        """Return whether physical channel rows include analogue input limits."""
        return (
            self._task_kind is DaqmxTaskKind.ACQUISITION
            and self._channel_family is DaqmxChannelFamily.ANALOG
        )

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
            terminal_configuration=DaqmxTerminalConfiguration(
                self.terminal_configuration_combo.currentData()
            ),
            input_ranges=self._selected_input_ranges(),
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
            self._populate_physical_channels(
                extra=definition.physical_channels,
                input_ranges=definition.input_ranges,
            )
            self._set_checked_tree_values(definition.physical_channels)
            self._select_combo_data(self.scale_combo, definition.custom_scale, add_missing=True)
            self._select_combo_data(
                self.terminal_configuration_combo,
                definition.terminal_configuration.value,
            )
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

    def _populate_physical_channels(
        self,
        *,
        extra: Iterable[str] = (),
        input_ranges: Iterable[DaqmxInputRange] = (),
    ) -> None:
        previous = set(self._checked_tree_values())
        configured = set(extra)
        selected = previous | configured
        ranges = self._input_range_map()
        ranges.update({item.channel: item for item in input_ranges})
        self.physical_tree.blockSignals(True)
        self.physical_tree.clear()
        self._range_widgets.clear()
        device_name = str(self.device_combo.currentData() or "")
        device = next((item for item in self._snapshot.devices if item.name == device_name), None)
        known: set[str] = set()
        if device is not None:
            for group_label, channels in device.channel_groups(
                self.task_kind(), self.channel_family()
            ):
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
                    self._add_range_widgets(child, channel, ranges.get(channel))
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
                self._add_range_widgets(child, channel, ranges.get(channel))
            group.setExpanded(True)
        self.physical_tree.blockSignals(False)

    def _add_range_widgets(
        self,
        item: QTreeWidgetItem,
        channel: str,
        input_range: DaqmxInputRange | None,
    ) -> None:
        """Add one per-channel symmetric analogue input range selector."""
        if not self._shows_input_ranges:
            return
        selected_range = input_range or DaqmxInputRange(channel)
        available_ranges = self._available_input_ranges()
        if available_ranges:
            selector: SIComboBox | SISpinBox = SIComboBox(
                unit="V", parent=self.physical_tree
            )
            for available_range in available_ranges:
                label = f"±{SIComboBox.format_si(available_range, 'V')}"
                selector.addValueItem(available_range, label=label)
            if selected_range.range not in available_ranges:
                selector.addValueItem(
                    selected_range.range,
                    label=f"±{SIComboBox.format_si(selected_range.range, 'V')} (configured)",
                )
            selector.setFloatValue(selected_range.range)
            selector.valueChanged.connect(lambda *_args: self._emit_definition_changed())
        else:
            selector = SISpinBox(value=selected_range.range)
            selector.setOpts(
                bounds=(1.0e-12, 1.0e9),
                decimals=6,
                suffix="V",
                siPrefix=True,
            )
            selector.sigValueChanged.connect(lambda *_args: self._emit_definition_changed())
        selector.setMaximumWidth(130)
        self.physical_tree.setItemWidget(item, 1, selector)
        self._range_widgets[channel] = selector

    def _available_input_ranges(self) -> tuple[float, ...]:
        """Return ranges advertised by the currently selected DAQmx device."""
        device_name = str(self.device_combo.currentData() or "")
        device = next((item for item in self._snapshot.devices if item.name == device_name), None)
        return () if device is None else device.analog_input_ranges

    def _input_range_map(self) -> dict[str, DaqmxInputRange]:
        """Return the currently displayed physical input ranges by channel."""
        return {
            channel: DaqmxInputRange(channel, self._range_widget_value(selector))
            for channel, selector in self._range_widgets.items()
        }

    @staticmethod
    def _range_widget_value(selector: SIComboBox | SISpinBox) -> float:
        """Return the numeric value from either range-selector variant."""
        if isinstance(selector, SIComboBox):
            return selector.currentFloatValue()
        return float(selector.value())

    def _selected_input_ranges(self) -> tuple[DaqmxInputRange, ...]:
        """Return ranges for selected physical analogue input channels."""
        ranges = self._input_range_map()
        return tuple(
            ranges[channel] for channel in self._checked_tree_values() if channel in ranges
        )

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
        family = self.channel_family()
        return tuple(
            resource
            for resource in resources
            if resource.task_kind in {None, kind}
            and (family is None or resource.channel_family is family)
        )

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
    "DaqmxChannelFamily",
    "DaqmxDeviceInfo",
    "DaqmxDiscoveryError",
    "DaqmxInputRange",
    "DaqmxNamedResource",
    "DaqmxSelectionMode",
    "DaqmxSystemInfo",
    "DaqmxTaskDefinition",
    "DaqmxTaskDefinitionWidget",
    "DaqmxTaskKind",
    "DaqmxTerminalConfiguration",
    "discover_daqmx_system",
]
