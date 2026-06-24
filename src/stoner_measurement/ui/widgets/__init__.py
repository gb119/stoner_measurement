"""Standard reusable widgets for stoner_measurement UIs.

Collects custom :mod:`PyQt6` compound widgets that are shared across
multiple measurement panels and dialogs.
"""

from stoner_measurement.ui.widgets.percent_slider import PercentSliderWidget
from stoner_measurement.ui.widgets.si_combo_box import SIComboBox
from stoner_measurement.ui.widgets.round_dial import RoundDialWidget
from stoner_measurement.ui.widgets.round_dial_demo import RoundDialDemoWidget
from stoner_measurement.ui.widgets.round_dial_panel import RoundDialPanel
from stoner_measurement.ui.widgets.si_spinbox import SISpinBox
from stoner_measurement.ui.widgets.visa_resource_widget import (
    FILTER_ALL,
    FILTER_GPIB,
    FILTER_SERIAL,
    VisaInterfaceType,
    VisaResourceComboBox,
    VisaResourceStatus,
    list_visa_resources,
)
from stoner_measurement.ui.widgets.controller_connection import (
    load_connection_preferences,
    restore_preferred_address,
    selected_transport,
    set_address_widget_status,
    show_transport_widget,
)

__all__ = [
    "FILTER_ALL",
    "FILTER_GPIB",
    "FILTER_SERIAL",
    "RoundDialWidget",
    "RoundDialDemoWidget",
    "RoundDialPanel",
    "PercentSliderWidget",
    "SIComboBox",
    "SISpinBox",
    "load_connection_preferences",
    "restore_preferred_address",
    "selected_transport",
    "set_address_widget_status",
    "show_transport_widget",
    "VisaInterfaceType",
    "VisaResourceComboBox",
    "VisaResourceStatus",
    "list_visa_resources",
]
