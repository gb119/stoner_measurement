"""Standard reusable widgets for stoner_measurement UIs.

Collects custom :mod:`PyQt6` compound widgets that are shared across
multiple measurement panels and dialogs.
"""

from stoner_measurement.ui.widgets.apt_controller_widget import AptControllerComboBox
from stoner_measurement.ui.widgets.auto_si_spinbox import AutoSISpinBox
from stoner_measurement.ui.widgets.controller_connection import (
    load_connection_preferences,
    restore_connection_address,
    restore_preferred_address,
    selected_transport,
    set_address_widget_status,
    show_transport_widget,
)
from stoner_measurement.ui.widgets.daqmx_task_widget import (
    DaqmxChannelFamily,
    DaqmxDeviceInfo,
    DaqmxDiscoveryError,
    DaqmxInputRange,
    DaqmxNamedResource,
    DaqmxSelectionMode,
    DaqmxSystemInfo,
    DaqmxTaskDefinition,
    DaqmxTaskDefinitionWidget,
    DaqmxTaskKind,
    DaqmxTerminalConfiguration,
    discover_daqmx_system,
)
from stoner_measurement.ui.widgets.daqmx_trigger_widget import (
    DaqmxInputTrigger,
    DaqmxInputTriggerMode,
    DaqmxInputTriggerWidget,
    DaqmxOutputTrigger,
    DaqmxOutputTriggerWidget,
    DaqmxTriggerEdge,
    DaqmxTriggerIdleState,
    DaqmxTriggerPulsePreview,
)
from stoner_measurement.ui.widgets.percent_slider import PercentSliderWidget
from stoner_measurement.ui.widgets.round_dial import RoundDialWidget
from stoner_measurement.ui.widgets.round_dial_demo import RoundDialDemoWidget
from stoner_measurement.ui.widgets.round_dial_panel import RoundDialPanel
from stoner_measurement.ui.widgets.si_combo_box import SIComboBox
from stoner_measurement.ui.widgets.si_spinbox import SISpinBox
from stoner_measurement.ui.widgets.visa_resource_widget import (
    FILTER_ALL,
    FILTER_GPIB,
    FILTER_SERIAL,
    StatusLineEdit,
    VisaInterfaceType,
    VisaResourceComboBox,
    VisaResourceStatus,
    list_visa_resources,
)

__all__ = [
    "FILTER_ALL",
    "FILTER_GPIB",
    "FILTER_SERIAL",
    "AptControllerComboBox",
    "AutoSISpinBox",
    "DaqmxChannelFamily",
    "DaqmxDeviceInfo",
    "DaqmxDiscoveryError",
    "DaqmxInputTrigger",
    "DaqmxInputRange",
    "DaqmxInputTriggerMode",
    "DaqmxInputTriggerWidget",
    "DaqmxNamedResource",
    "DaqmxOutputTrigger",
    "DaqmxOutputTriggerWidget",
    "DaqmxSelectionMode",
    "DaqmxSystemInfo",
    "DaqmxTaskDefinition",
    "DaqmxTaskDefinitionWidget",
    "DaqmxTaskKind",
    "DaqmxTerminalConfiguration",
    "DaqmxTriggerEdge",
    "DaqmxTriggerIdleState",
    "DaqmxTriggerPulsePreview",
    "RoundDialWidget",
    "RoundDialDemoWidget",
    "RoundDialPanel",
    "PercentSliderWidget",
    "SIComboBox",
    "SISpinBox",
    "StatusLineEdit",
    "load_connection_preferences",
    "restore_connection_address",
    "restore_preferred_address",
    "selected_transport",
    "set_address_widget_status",
    "show_transport_widget",
    "discover_daqmx_system",
    "VisaInterfaceType",
    "VisaResourceComboBox",
    "VisaResourceStatus",
    "list_visa_resources",
]
