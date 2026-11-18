"""Model and quantity catalogue shared by electrometer sequence plugins."""

from stoner_measurement.instruments.electrometer import ElectrometerFunction
from stoner_measurement.instruments.keithley import Keithley6485, Keithley6514, Keithley6517

ELECTROMETER_DRIVERS = {
    "keithley_6485": Keithley6485,
    "keithley_6514": Keithley6514,
    "keithley_6517": Keithley6517,
}
FUNCTION_CHANNELS = {
    ElectrometerFunction.CURR: ("Current", "A"),
    ElectrometerFunction.VOLT: ("Voltage", "V"),
    ElectrometerFunction.RES: ("Resistance", "Ω"),
    ElectrometerFunction.CHARGE: ("Charge", "C"),
}
