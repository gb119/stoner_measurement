"""Stable centre-panel host for one GUI-owned measurement display."""

import json
import logging
from dataclasses import replace

from qtpy.QtCore import QThread  # type: ignore[attr-defined]
from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget

from stoner_measurement.core.plotting.contracts import (
    AxisDescription,
    ConfigureAxes,
    PlotRequest,
    SeriesDescription,
)
from stoner_measurement.core.plotting.service import PlotService, UnsupportedDisplayOperation
from stoner_measurement.core.plotting.state import (
    DisplayState,
    SeriesState,
    freeze_settings,
    settings_dict,
)
from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.ui.plotting.interfaces import PlotDisplay
from stoner_measurement.ui.plotting.registry import PlotDisplayRegistry

logger = logging.getLogger(__name__)


class PlotDisplayHost(QWidget):
    """Own a startup-selected display and its stable producer service.

    Args:
        parent (QWidget | None): Owning application panel.
        registry (PlotDisplayRegistry | None): Discovered factories; discover
            installed factories when omitted.
        factory_id (str): Startup selection, falling back to Cartesian on error.

    Replacement requires an idle service and engine; failed candidates leave
    the current display in place. Preferences exclude measurement arrays.
    ``display_widget`` is the explicit GUI inspection/Cartesian escape accessor.
    """

    changed = pyqtSignal()
    display_changed = pyqtSignal(str)

    def __init__(
        self, parent=None, *, registry=None, factory_id=None, settings=None, idle_check=None
    ) -> None:
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError("Plot displays must be constructed on the GUI thread.")
        super().__init__(parent)
        self.registry = registry if registry is not None else PlotDisplayRegistry()
        if registry is None:
            self.registry.discover()
        self._diagnostics = list(self.registry.diagnostics)
        self._closed = False
        self.switch_requires_reset = False
        self._settings = settings
        self._settings_cache: dict[str, dict] = {}
        self._hidden_styles: dict[str, dict] = {}
        self.idle_check = idle_check or (lambda: True)
        self._display: PlotDisplay
        self._container: QWidget
        saved_id = self._load_preferences()
        factory_id = factory_id or saved_id or "cartesian"
        self.factory_id = factory_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        created = False
        try:
            self._display, self._container = self._create(factory_id)
            created = True
            self._restore_preferences(self._display, factory_id)
        except Exception as exc:
            if factory_id == "cartesian" and not created:
                raise  # Failure of the guaranteed default cannot be hidden.
            message = f"Plot display {factory_id!r} unavailable: {exc}; using Cartesian."
            self._diagnostics.append(message)
            logger.warning(message)
            self.factory_id = "cartesian"
            self._settings_cache.pop("cartesian", None)
            if hasattr(self, "_display"):
                self._dispose(self._display, self._container)
            self._display, self._container = self._create("cartesian")
        self._display.changed.connect(self.changed)
        layout.addWidget(self._container)
        self.service = PlotService(self, parent=self)

    def _create(self, factory_id: str):
        factory = self.registry.get(factory_id)
        if factory is None:
            raise ValueError("Unknown display factory.")
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        display = None
        try:
            display = factory.create(container)
            self._validate_display(display, container, factory)
            layout.addWidget(display.widget)
        except Exception:
            closed_widget = None
            if display is not None and callable(getattr(display, "close", None)):
                try:
                    display.close()
                    closed_widget = getattr(display, "widget", None)
                except Exception as exc:
                    logger.warning("Failed display cleanup: %s", exc)
            for child in container.findChildren(QWidget):
                if child.parent() is container and child is not closed_widget:
                    child.close()
            container.close()
            container.deleteLater()
            raise
        return display, container

    def _validate_display(self, display, container, factory) -> None:
        """Check widget ownership and the adapter contract before connecting it."""
        if not isinstance(display.widget, QWidget) or display.widget.thread() != self.thread():
            raise TypeError("A display must supply a GUI-thread QWidget.")
        if display.widget.parent() is not container:
            raise ValueError("A display widget must belong to its supplied parent.")
        if display.capabilities != factory.capabilities:
            raise ValueError("Display capabilities must match factory metadata.")
        for name in ("validate", "apply", "descriptions", "close"):
            if not callable(getattr(display, name, None)):
                raise TypeError(f"Missing display method: {name}.")
        if not callable(getattr(getattr(display, "changed", None), "connect", None)):
            raise TypeError("A display must supply a changed signal.")
        if not callable(getattr(display.changed, "disconnect", None)):
            raise TypeError("A display signal must support disconnection.")
        axes, series = display.descriptions()
        self._validate_descriptions(axes, series, "Invalid portable display descriptions.")

    @staticmethod
    def _validate_descriptions(axes, series, message) -> None:
        """Require immutable tuples of portable axis and series descriptions."""
        if (
            not isinstance(axes, tuple)
            or not isinstance(series, tuple)
            or any(
                not isinstance(item, kind)
                for items, kind in ((axes, AxisDescription), (series, SeriesDescription))
                for item in items
            )
        ):
            raise TypeError(message)

    def _load_preferences(self):
        if self._settings is None:
            return None
        try:
            raw = self._settings.value("plotDisplay/preferences", "")
            if not raw:
                return None
            saved = json.loads(raw)
            if saved.get("version") != 1 or not isinstance(saved.get("renderers"), dict):
                raise ValueError("Unsupported display preferences version.")
            freeze_settings(saved)
            self._settings_cache = saved["renderers"]
            return saved["factory_id"]
        except Exception as exc:
            self._diagnostics.append(f"Ignored invalid display preferences: {exc}")
            return None

    def _restore_preferences(self, display, factory_id):
        preferences = self._settings_cache.get(factory_id, {})
        if preferences:
            importer = getattr(display, "import_settings", None)
            if not callable(importer):
                raise ValueError("The display cannot restore its saved preferences.")
            importer(preferences)

    def save_preferences(self) -> None:
        """Persist factory and versioned renderer settings, never measurement arrays."""
        exporter = getattr(self._display, "export_settings", None)
        if callable(exporter):
            preferences = settings_dict(freeze_settings(exporter()))
            self._settings_cache[self.factory_id] = preferences
        if self._settings is not None:
            self._settings.setValue(
                "plotDisplay/preferences",
                json.dumps(
                    {
                        "version": 1,
                        "factory_id": self.factory_id,
                        "renderers": self._settings_cache,
                    }
                ),
            )

    def export_state(self) -> DisplayState:
        """Capture current UI state and canonical source channels on the GUI thread."""
        if not self.service.is_gui_thread():
            raise RuntimeError("State export must run on the GUI thread.")
        exporter = getattr(self._display, "export_state", None)
        if not callable(exporter):
            raise UnsupportedDisplayOperation("The current display cannot export replay state.")
        state = exporter()
        if not isinstance(state, DisplayState):
            raise TypeError("Invalid display state export.")
        state = self.service.export_state(state)
        return replace(
            state,
            series=tuple(
                SeriesState(
                    replace(
                        entry.update,
                        style={
                            **dict(entry.update.style),
                            **self._hidden_styles.get(entry.update.series_id, {}),
                        },
                    ),
                    entry.visible,
                )
                for entry in state.series
            ),
        )

    def _prepare_state(self, state, display, factory_id):
        series = []
        hidden = {}
        supported_styles = getattr(display, "supported_styles", None)
        for entry in state.series:
            update = entry.update
            if supported_styles is not None:
                unsupported = {
                    key: value for key, value in update.style.items() if key not in supported_styles
                }
                if unsupported:
                    hidden[update.series_id] = unsupported
                    self._diagnostics.append(
                        f"Display {factory_id!r} retains unsupported styles for {update.series_id!r}: {', '.join(unsupported)}"
                    )
                update = replace(
                    update,
                    style={
                        key: value for key, value in update.style.items() if key in supported_styles
                    },
                )
            reasons = display.capabilities.unsupported_reasons(PlotRequest(update))
            if reasons:
                raise UnsupportedDisplayOperation(
                    f"Series {update.series_id!r}: {' '.join(reasons)}"
                )
            series.append(SeriesState(update, entry.visible))
        for payload in ([ConfigureAxes(state.axes)] if state.axes else []) + [
            entry.marker for entry in state.markers
        ]:
            reasons = display.capabilities.unsupported_reasons(PlotRequest(payload))
            if reasons:
                raise UnsupportedDisplayOperation(" ".join(reasons))
        preferences = self._settings_cache.get(factory_id, {})
        return replace(state, series=tuple(series), renderer_settings=preferences), hidden

    def _dispose(self, display, container):
        try:
            display.close()
        finally:
            container.hide()
            container.deleteLater()

    def switch_display(self, factory_id: str, *, force=False, reset=False) -> bool:
        """Switch while idle, optionally discarding plotted state at successful commit.

        A reset uses the candidate's default axes and settings. Failures retain
        the current display/data; switch_requires_reset identifies replay refusals.
        """
        self.switch_requires_reset = False
        if not self.service.is_gui_thread():
            raise RuntimeError("Display replacement must run on the GUI thread.")
        if factory_id == self.factory_id and not force:
            return True
        candidate = container = None
        replaying = False
        try:
            with self.service.replacement_guard():
                if not self.idle_check():
                    raise RuntimeError("Display replacement requires an idle measurement engine.")
                state = self.export_state()
                self._settings_cache[self.factory_id] = settings_dict(state.renderer_settings)
                candidate, container = self._create(factory_id)
                container.resize(self._container.size())
                container.layout().activate()
                candidate.widget.resize(self._display.widget.size())
                replaying = True
                state, hidden = self._replay_state(state, candidate, factory_id, reset=reset)
                replaying = False
                # Re-read descriptions before commit: malformed hydrated state is a failure.
                axes, series = candidate.descriptions()
                self._validate_descriptions(axes, series, "Invalid hydrated display descriptions.")
                if {entry.series_id for entry in series} != {
                    entry.update.series_id for entry in state.series
                }:
                    raise ValueError("The candidate did not hydrate every series.")
                if not self.idle_check():
                    raise RuntimeError("The measurement engine became busy during replacement.")
                candidate.changed.connect(self.changed)
                old_display, old_container = self._display, self._container
                old_display.changed.disconnect(self.changed)
                self._display, self._container = candidate, container
                self.factory_id = factory_id
                self._hidden_styles = hidden
                self.layout().replaceWidget(old_container, container)
                container.show()
                self.service.commit_replacement(state, (axes, series))
                candidate = container = None
                try:
                    self._dispose(old_display, old_container)
                except Exception as exc:
                    self._diagnostics.append(f"Old display cleanup failed: {exc}")
                try:
                    self.save_preferences()
                except Exception as exc:
                    self._diagnostics.append(f"Display preferences could not be saved: {exc}")
                self.display_changed.emit(factory_id)
            return True
        except Exception as exc:
            self.switch_requires_reset = replaying and isinstance(
                exc, (UnsupportedDisplayOperation, ValueError)
            )
            self._diagnostics.append(f"Could not switch to {factory_id!r}: {exc}")
            logger.warning(self._diagnostics[-1])
            return False
        finally:
            if candidate is not None:
                try:
                    self._dispose(candidate, container)
                except Exception as exc:
                    self._diagnostics.append(f"Candidate cleanup failed: {exc}")

    def _replay_state(self, state, candidate, factory_id, *, reset):
        """Prepare and import replay state before committing a display replacement."""
        if reset:
            state = candidate.export_state()
            if not isinstance(state, DisplayState):
                raise TypeError("Invalid display state export.")
            state = replace(state, series=(), markers=())
            hidden = {}
        else:
            state, hidden = self._prepare_state(state, candidate, factory_id)
        importer = getattr(candidate, "import_state", None)
        if not callable(importer):
            raise UnsupportedDisplayOperation("The selected display cannot import replay state.")
        if not callable(getattr(candidate, "export_state", None)):
            raise UnsupportedDisplayOperation("The selected display cannot import replay state.")
        importer(state)
        return state, hidden

    @property
    def display(self) -> PlotDisplay:
        """Return the active adapter for GUI inspection."""
        return self._display

    @property
    def display_widget(self) -> QWidget:
        """Return the current concrete widget outside the portable client API."""
        return self._display.widget

    @property
    def diagnostics(self) -> tuple[str, ...]:
        """Return discovery and startup-fallback diagnostics."""
        return tuple(self._diagnostics)

    @property
    def capabilities(self):
        """Expose the selected display's portable capabilities."""
        return self._display.capabilities

    def descriptions(self):
        """Read portable descriptions on the GUI dispatcher."""
        return self._display.descriptions()

    def validate(self, payload) -> None:
        """Delegate validation without knowing the rendering library."""
        supported = getattr(self._display, "supported_styles", None)
        if supported is not None and set(getattr(payload, "style", {})).difference(supported):
            raise UnsupportedDisplayOperation(
                "The selected display does not support these style options."
            )
        self._display.validate(payload)

    def apply(self, payload):
        """Apply one portable operation through the active adapter."""
        return self._display.apply(payload)

    def _legacy_method(self, name):
        method = getattr(self._display, name, None)
        if not callable(method):
            raise UnsupportedDisplayOperation("The selected display has no Cartesian legacy API.")
        return method

    def normalize_legacy(self, call):
        """Use optional Cartesian compatibility, never require it of a plugin."""
        return self._legacy_method("normalize_legacy")(call)

    def legacy_update(self, call, existing):
        """Translate optional Cartesian data calls."""
        return self._legacy_method("legacy_update")(call, existing)

    def call_legacy(self, call):
        """Apply optional Cartesian compatibility operations."""
        return self._legacy_method("call_legacy")(call)

    def closeEvent(self, event) -> None:
        """Stop requests before explicitly closing owned graphics resources."""
        if not self._closed:
            self._closed = True
            try:
                self.save_preferences()
            except Exception as exc:
                logger.warning("Display preferences could not be saved during close: %s", exc)
            self.service.shutdown()
            self._display.changed.disconnect(self.changed)
            self._display.close()
        super().closeEvent(event)
