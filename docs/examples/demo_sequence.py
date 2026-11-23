"""A minimal sequence container with a shared direct and generated action."""

from stoner_measurement.plugins.sequence import SequencePlugin


class DemoSequencePlugin(SequencePlugin):
    """Log the start of a group and run its children in order."""

    @property
    def name(self):
        return "Demo Group"

    @property
    def has_lifecycle(self):
        return False

    def log_start(self):
        """Log the start of this group using its sequence instance name."""
        self.log.info("Starting %s", self.instance_name)

    def execute_sequence(self, sub_steps):
        """Log the start, then call each child in order."""
        self.log_start()
        for sub_step in sub_steps:
            sub_step()

    def generate_action_code(self, indent, sub_steps, render_sub_step):
        """Generate the same action before rendering the child steps."""
        prefix = "    " * indent
        return [
            f"{prefix}{self.instance_name}.log_start()",
            *super().generate_action_code(indent, sub_steps, render_sub_step),
        ]
