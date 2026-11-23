"""A minimal transform that publishes a scalar from a trace."""

from stoner_measurement.plugins import PluginOutputs, ScalarOutput
from stoner_measurement.plugins.transform import TransformPlugin


class DemoTransformPlugin(TransformPlugin):
    """Calculate the mean voltage from an earlier Demo Trace step."""

    @property
    def name(self):
        return "Demo Mean Voltage"

    @property
    def required_inputs(self):
        return []

    def declared_outputs(self):
        """Publish the stored mean voltage as a scalar in volts."""
        var = self.instance_name
        return PluginOutputs(
            values={
                f"{var}:Mean Voltage": ScalarOutput(
                    f"{var}.data['mean_voltage']",
                    units="V",
                    result_key="mean_voltage",
                ),
            }
        )

    def transform(self, data):
        """Read the completed trace from the live sequence namespace."""
        trace = self.engine_namespace["demo_trace"].data["Demo Trace"]
        return {"mean_voltage": float(trace.df["y"].mean())}
