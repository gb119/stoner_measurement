# stoner_measurement

[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://gb119.github.io/stoner_measurement/)

A Python QT6 application for carrying out scientific measurements.

## Writing a Plugin

All measurement plugins inherit from `BasePlugin` and must implement two
members:

| Member | Type | Required | Description |
|--------|------|----------|-------------|
| `name` | `property → str` | **Yes** | Unique human-readable identifier. |
| `execute(parameters)` | `Generator[tuple[float, float]]` | **Yes** | Yields `(x, y)` data points. |

### Optional UI integration

Plugins can hook into the main window UI by overriding any of the following
methods.

#### `config_tabs(parent=None) → list[tuple[str, QWidget]]`

Returns a list of `(tab_title, widget)` pairs.  Each pair becomes one tab in
the right-hand **configuration panel**.

The default implementation wraps `config_widget()` in a single-element list
using `name` as the tab title.  Override `config_tabs()` directly when a
plugin needs **more than one tab** or a custom tab title.

```python
def config_tabs(self, parent=None):
    settings = self.config_widget(parent=parent)
    about    = QLabel("My plugin v1.0", parent)
    return [
        ("MyPlugin – Settings", settings),
        ("MyPlugin – About",    about),
    ]
```

#### `config_widget(parent=None) → QWidget`

Returns a single `QWidget`.  Used by the default `config_tabs()`
implementation — override this when a single tab is sufficient.

#### `monitor_widget(parent=None) → QWidget | None`

Returns an optional live-status widget shown in the **left dock panel**
*Monitoring* section while the plugin is registered.  Return `None` (the
default) if no monitoring widget is needed.

```python
def monitor_widget(self, parent=None):
    self._status_label = QLabel("Idle", parent)
    return self._status_label
```

### Minimal example

```python
from stoner_measurement.plugins.base_plugin import BasePlugin

class ThermometerPlugin(BasePlugin):
    @property
    def name(self):
        return "Thermometer"

    def execute(self, parameters):
        for reading in self._hardware.read(parameters.get("samples", 10)):
            yield reading.time, reading.temperature
```

### Registering a plugin

Plugins are discovered via Python
[entry-points](https://packaging.python.org/en/latest/specifications/entry-points/):

```toml
[project.entry-points."stoner_measurement.plugins"]
thermometer = "my_package.thermometer:ThermometerPlugin"
```

