"""A minimal external sequence command with configuration and scalar output."""

from qtpy.QtWidgets import QFormLayout, QLineEdit, QVBoxLayout, QWidget

from stoner_measurement.plugins.command import CommandPlugin


class RecordValueCommand(CommandPlugin):
    """Evaluate a numeric expression, publish its result, and log the value.

    Configure the expression and its units on General. The expression is
    evaluated when the step executes; Value is available to Plot Points and
    scan/sweep collection. This command owns no instrument resources.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value_expr = "1.0"
        self.value_units = ""
        self.value = float("nan")

    @property
    def name(self):
        return "Record Value"

    def execute(self):
        self.value = float("nan")
        self.value = self.eval_float(self.value_expr)
        self.log.info("%s: %s %s", self.instance_name, self.value, self.value_units)

    def reported_values(self):
        return {f"{self.instance_name}:Value": f"{self.instance_name}.value"}

    def reported_value_units(self):
        return {f"{self.instance_name}:Value": self.value_units}

    def config_widget(self, parent=None):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        expression = QLineEdit(self.value_expr, widget)
        units = QLineEdit(self.value_units, widget)

        def apply_settings():
            self.value_expr = expression.text().strip()
            self.value_units = units.text().strip()
            if self.sequence_engine is not None:
                self.sequence_engine.refresh_data_catalogs()

        expression.editingFinished.connect(apply_settings)
        units.editingFinished.connect(apply_settings)
        form.addRow("Value expression:", expression)
        form.addRow("Units:", units)
        layout.addLayout(form)
        layout.addStretch()
        return widget

    def to_json(self):
        data = super().to_json()
        data.update(value_expr=self.value_expr, value_units=self.value_units)
        return data

    def _restore_from_json(self, data):
        super()._restore_from_json(data)
        self.value_expr = data.get("value_expr", self.value_expr)
        self.value_units = data.get("value_units", self.value_units)
