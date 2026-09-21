"""Aggregation and routing for two independently owned temperature sessions."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from stoner_measurement.temperature_control.references import (
    ChannelRef,
    LoopRef,
    channel_ref,
    controller_id,
    loop_ref,
)
from stoner_measurement.temperature_control.types import EngineStatus


@dataclass(frozen=True)
class TemperatureDescriptor:
    """A stable reference with its owner's capabilities and display label."""

    reference: LoopRef | ChannelRef
    label: str
    capabilities: object


class TemperatureServiceMixin:
    """Route qualified operations and aggregate isolated controller sessions."""

    def controller(self, slot="primary"):
        """Return the session for a persistent slot; primary retains legacy APIs."""
        controller_id(slot)
        return self if slot == "primary" else self._secondary

    @property
    def controllers(self):
        """Return sessions in stable primary/secondary order."""
        return {"primary": self, "secondary": self._secondary}

    def set_controller_enabled(self, slot, enabled):
        """Enable a slot, or disconnect it before disabling it."""
        session = self.controller(slot)
        if not enabled:
            session.disconnect_instrument()
        self._enabled[slot] = bool(enabled)
        self.publisher.connection_changed.emit()

    def controller_enabled(self, slot):
        """Return whether automatic connection of this slot is permitted."""
        return self._enabled[controller_id(slot)]

    def ensure_controller(self, slot="primary"):
        """Connect a requested enabled slot, or report an explicit failure."""
        session = self.controller(slot)
        if session.connected_driver is None:
            if not self.controller_enabled(slot):
                raise RuntimeError(f"Temperature controller {slot} is disabled.")
            session.connect_preferred_driver()
        if session.connected_driver is None:
            raise RuntimeError(f"Temperature controller {slot} is unavailable.")
        return session

    def loop_catalogue(self):
        """List loops with their own capabilities, independent of peer topology."""
        result = []
        for slot, session in self.controllers.items():
            if session.connected_driver is None:
                continue
            caps = session.connected_driver.get_capabilities()
            for local in caps.loop_numbers:
                ref = LoopRef(slot, local)
                result.append(TemperatureDescriptor(ref, str(ref), caps))
        return result

    def channel_catalogue(self):
        """List all sensors without merging identical native names."""
        result = []
        for slot, session in self.controllers.items():
            if session.connected_driver is None:
                continue
            caps = session.connected_driver.get_capabilities()
            for local in caps.input_channels:
                ref = ChannelRef(slot, local)
                result.append(TemperatureDescriptor(ref, str(ref), caps))
        return result

    def loop_input_channels(self, loop):
        """Return only qualified inputs that this loop can control."""
        ref = loop_ref(loop)
        session = self.controller(ref.controller_id)
        driver = session.connected_driver
        if driver is None:
            return ()
        method = getattr(driver, "get_loop_input_channels", None)
        channels = method(ref.loop) if method else driver.get_capabilities().input_channels
        return tuple(ChannelRef(ref.controller_id, ch) for ch in channels)

    def _check_driver(self, slot, driver):
        from stoner_measurement.instruments.transport import NullTransport

        transport = getattr(driver, "transport", None)
        for other, session in self.controllers.items():
            peer = session.connected_driver
            if other == slot or peer is None:
                continue
            if driver is peer:
                raise ValueError("Both controller slots cannot own the same driver.")
            peer_transport = getattr(peer, "transport", None)
            if (
                transport is not None
                and peer_transport is not None
                and not isinstance(transport, NullTransport)
            ):
                if transport is peer_transport or transport.lock_key == peer_transport.lock_key:
                    raise ValueError(f"Temperature controller {other} already owns this transport.")

    def _check_connection(self, slot, transport, address):
        """Reject duplicate physical endpoints before opening a second handle."""
        key = self._connection_key(transport, address)
        if key is None:
            return
        for other, session in self.controllers.items():
            if other != slot and session.connected_driver is not None:
                existing = self._connection_key(
                    session.connected_transport_name or "", session.connected_address or ""
                )
                if existing == key:
                    raise ValueError(
                        f"Temperature controller {other} already owns this connection."
                    )

    @staticmethod
    def _connection_key(transport, address):
        from stoner_measurement.instruments.addressing import (
            parse_ethernet_address,
            parse_serial_address,
        )

        transport = transport.strip().lower()
        if transport.startswith("null"):
            return None
        if transport == "serial":
            port, _baud = parse_serial_address(address)
            return (transport, port.casefold())
        if transport == "ethernet":
            host, port = parse_ethernet_address(address)
            return (transport, host.casefold(), port)
        return (transport, address.strip().casefold())

    def _resolve_loop(self, loop):
        ref = loop_ref(loop)
        session = self.controller(ref.controller_id)
        if session.connected_driver is None:
            raise RuntimeError(f"Temperature controller {ref.controller_id} is disconnected.")
        if ref.loop not in session.connected_driver.get_capabilities().loop_numbers:
            raise ValueError(f"Unavailable temperature loop: {ref}")
        return session, ref.loop

    def _resolve_channel(self, channel):
        ref = channel_ref(channel)
        session = self.controller(ref.controller_id)
        if session.connected_driver is None:
            raise RuntimeError(f"Temperature controller {ref.controller_id} is disconnected.")
        if ref.channel not in session.connected_driver.get_capabilities().input_channels:
            raise ValueError(f"Unavailable temperature channel: {ref}")
        return session, ref.channel

    @property
    def status(self):
        """Aggregate health; a failed session does not hide healthy peer data."""
        if self._status is EngineStatus.STOPPED:
            return self._status
        secondary = getattr(self, "_secondary", None)
        statuses = [self._status]
        if secondary is not None:
            statuses.append(secondary.status)
        for status in (EngineStatus.ERROR, EngineStatus.POLLING, EngineStatus.CONNECTED):
            if status in statuses:
                return status
        return EngineStatus.DISCONNECTED

    def _session_changed(self):
        if self._secondary.connected_driver is not None:
            self._enabled["secondary"] = True
        self._refresh_timer()
        self.publisher.engine_status_changed.emit(self.status)
        self.publisher.connection_changed.emit()
        self.publisher.state_updated.emit(self.get_engine_state())

    def _refresh_timer(self):
        if not hasattr(self, "_secondary"):
            return
        self._secondary._timer.stop()
        if self.polling_rate_hz > 0 and any(
            s.connected_driver is not None for s in self.controllers.values()
        ):
            self._timer.start()
        else:
            self._timer.stop()

    def set_polling_rate(self, rate_hz):
        """Set the common polling cadence for both sessions."""
        super().set_polling_rate(rate_hz)
        if hasattr(self, "_secondary"):
            self._secondary.set_polling_rate(rate_hz)
            self._refresh_timer()

    def read_controller_state(self):
        """Poll both sessions independently and publish one consolidated snapshot."""
        if self.connected_driver is None and self._secondary.connected_driver is None:
            return None
        primary = super().read_controller_state(publish=False, evaluate_stability=False)
        secondary = self._secondary.read_controller_state(publish=False, evaluate_stability=False)
        self._evaluate_shared_stability()
        state = self.get_engine_state()
        self.publisher.engine_status_changed.emit(self.status)
        for reading in state.all_readings.values():
            self.publisher.channel_reading.emit(reading)
        self.publisher.state_updated.emit(state)
        if primary is not None or secondary is not None:
            self.publisher.poll_activity.emit()
        return state

    def set_stability_config(self, config):
        """Apply one ordered stability table to every loop on the rig."""
        super().set_stability_config(config)
        if hasattr(self, "_secondary"):
            # Reset the peer without delegating its public setter back here.
            self._secondary._stability_config = config
            self._secondary._at_setpoint_since.clear()
            self._secondary._unstable_since.clear()
            self._secondary._stable.clear()
            self._secondary._stability_value_history.clear()
            self._secondary._stability_diagnostics.clear()
            self._secondary._stability_sources.clear()
            state = self._secondary._latest_state
            self._secondary._latest_state = replace(
                state,
                stable={loop: False for loop in state.stable},
                at_setpoint={loop: False for loop in state.at_setpoint},
                stability_diagnostics={},
            )

    def _shared_stability_readings(self):
        """Use only fresh successful snapshots from the completed polling cycle."""
        return {
            (f"secondary:{channel}" if slot == "secondary" else channel): reading
            for slot, session in self.controllers.items()
            if session.connected_driver is not None
            and session.state_cache_age_seconds <= session._freshness_limit
            for channel, reading in session._latest_state.readings.items()
        }

    def _evaluate_shared_stability(self):
        readings = self._shared_stability_readings()
        now = datetime.now(tz=UTC)
        for session in self.controllers.values():
            state = session._latest_state
            loops = tuple(state.setpoints)
            at_setpoint, stable = session._evaluate_stability(readings, state.setpoints, loops, now)
            session._latest_state = replace(
                state,
                at_setpoint=at_setpoint,
                stable=stable,
                stability_rate_channels=session._select_stability_rate_channels(
                    readings, session._target_setpoints, loops
                ),
                stability_diagnostics=dict(session._stability_diagnostics),
            )

    def _stability_snapshot(self, session, state, readings):
        """Invalidate waits immediately when a referenced peer becomes unavailable."""
        from stoner_measurement.temperature_control.engine import (
            _reading_for_channel,
            _select_stability_band,
            _stability_channel_key,
        )

        unavailable = []
        for loop in state.stable:
            target = session._target_setpoints.get(loop, state.setpoints.get(loop, 0.0))
            band = _select_stability_band(self.stability_config, target)
            selected = tuple(
                _reading_for_channel(readings, channel)
                for channel in (band.tolerance_channel, band.rate_channel)
            )
            sources = (id(band), *(_stability_channel_key(reading) for reading in selected))
            if (
                any(reading is None for reading in selected)
                or session._stability_sources.get(loop) != sources
            ):
                unavailable.append(loop)
                session._at_setpoint_since.pop(loop, None)
                session._stable[loop] = False
        return replace(
            state,
            stable={k: v and k not in unavailable for k, v in state.stable.items()},
            at_setpoint={k: v and k not in unavailable for k, v in state.at_setpoint.items()},
        )

    def _chart_rate_channel(self, states, readings):
        """Resolve competing active bands by row priority, then stable loop order."""
        from stoner_measurement.temperature_control.engine import _select_stability_band

        candidates = []
        for slot, state in states.items():
            session = self.controller(slot)
            for loop in sorted(state.setpoints):
                target = session._target_setpoints.get(loop, state.setpoints.get(loop, 0.0))
                band = _select_stability_band(self.stability_config, target)
                channel = band.rate_channel or next(iter(readings), None)
                candidates.append((self.stability_config.bands.index(band), slot, loop, channel))
        if not candidates:
            return None
        channel = min(candidates)[-1]
        return channel

    def get_engine_state(self):
        """Return primary-compatible state with independent secondary state."""
        state = super().get_engine_state()
        if not hasattr(self, "_secondary"):
            return state
        secondary = self._secondary.get_engine_state(_local=True)
        readings = self._shared_stability_readings()
        state = self._stability_snapshot(self, state, readings)
        secondary = self._stability_snapshot(self._secondary, secondary, readings)
        return replace(
            state,
            stability_rate_channel=self._chart_rate_channel(
                {"primary": state, "secondary": secondary}, readings
            ),
            secondary=secondary,
            engine_status=self.status,
            controller_statuses={"primary": self._status, "secondary": self._secondary.status},
            cache_ages={
                "primary": self.state_cache_age_seconds,
                "secondary": self._secondary.state_cache_age_seconds,
            },
        )

    def configuration_dict(self):
        """Save both slots while retaining primary aliases for older consumers."""
        config = super().configuration_dict()
        controllers = {}
        for slot, session in self.controllers.items():
            local = (
                super().configuration_dict() if session is self else session.configuration_dict()
            )
            controllers[slot] = {
                "enabled": self._enabled[slot],
                "label": slot.title(),
                "connection": local["connection"],
            }
        config.update(schema_version=3, controllers=controllers)
        return config

    def shutdown(self):
        """Attempt both cleanups, preserving failures for the caller."""
        was_singleton = type(self)._singleton is self
        errors = []
        for close in (self._secondary.shutdown, super().shutdown):
            try:
                close()
            except Exception as error:
                errors.append(error)
        self._timer.stop()
        if errors:
            self._status = EngineStatus.ERROR
            if was_singleton:
                type(self)._singleton = self
            raise ExceptionGroup("Temperature controller shutdown failed", errors)

    def set_input_channel(self, loop, channel):
        """Validate ownership before assigning a native hardware input."""
        ref = loop_ref(loop)
        sensor = channel_ref(channel, ref.controller_id)
        if sensor not in self.loop_input_channels(ref):
            raise ValueError(f"{sensor} cannot control {ref}.")
        session, local = self._resolve_loop(ref)
        method = super().set_input_channel if session is self else session.set_input_channel
        return method(local, sensor.channel)

    def set_all_loop_settings(self, loop, **settings):
        """Validate all references before the first write in Apply All."""
        ref = loop_ref(loop)
        sensor = channel_ref(settings["input_channel"], ref.controller_id)
        if sensor not in self.loop_input_channels(ref):
            raise ValueError(f"{sensor} cannot control {ref}.")
        session, local = self._resolve_loop(ref)
        settings["input_channel"] = sensor.channel
        method = super().set_all_loop_settings if session is self else session.set_all_loop_settings
        return method(local, **settings)

    def set_setpoint(self, loop, value):
        """Route set setpoint to the owning controller."""
        session, local = self._resolve_loop(loop)
        method = super().set_setpoint if session is self else session.set_setpoint
        return method(local, value)

    def set_heater_range(self, loop, range_):
        """Route set heater range to the owning controller."""
        session, local = self._resolve_loop(loop)
        method = super().set_heater_range if session is self else session.set_heater_range
        return method(local, range_)

    def set_pid(self, loop, p, i, d):
        """Route set pid to the owning controller."""
        session, local = self._resolve_loop(loop)
        method = super().set_pid if session is self else session.set_pid
        return method(local, p, i, d)

    def set_ramp(self, loop, rate, enabled):
        """Route set ramp to the owning controller."""
        session, local = self._resolve_loop(loop)
        method = super().set_ramp if session is self else session.set_ramp
        return method(local, rate, enabled)

    def set_loop_mode(self, loop, mode):
        """Route set loop mode to the owning controller."""
        session, local = self._resolve_loop(loop)
        method = super().set_loop_mode if session is self else session.set_loop_mode
        return method(local, mode)

    def set_manual_heater_output(self, loop, output):
        """Route set manual heater output to the owning controller."""
        session, local = self._resolve_loop(loop)
        method = (
            super().set_manual_heater_output
            if session is self
            else session.set_manual_heater_output
        )
        return method(local, output)

    def get_zone_table(self, loop):
        """Route get zone table to the owning controller."""
        if not isinstance(loop, (LoopRef, ChannelRef, dict)) and self.connected_driver is None:
            return None
        session, local = self._resolve_loop(loop)
        method = super().get_zone_table if session is self else session.get_zone_table
        return method(local)

    def set_zone_table(self, loop, entries):
        """Route set zone table to the owning controller."""
        session, local = self._resolve_loop(loop)
        method = super().set_zone_table if session is self else session.set_zone_table
        return method(local, entries)

    def get_loop_settings(self, loop):
        """Route get loop settings to the owning controller."""
        if not isinstance(loop, (LoopRef, ChannelRef, dict)) and self.connected_driver is None:
            return None
        session, local = self._resolve_loop(loop)
        method = super().get_loop_settings if session is self else session.get_loop_settings
        return method(local)

    def get_input_channel_settings(self, channel):
        """Route get input channel settings to the owning controller."""
        if not isinstance(channel, (LoopRef, ChannelRef, dict)) and self.connected_driver is None:
            return None
        session, local = self._resolve_channel(channel)
        method = (
            super().get_input_channel_settings
            if session is self
            else session.get_input_channel_settings
        )
        return method(local)

    def set_input_channel_settings(self, channel, settings):
        """Route set input channel settings to the owning controller."""
        session, local = self._resolve_channel(channel)
        method = (
            super().set_input_channel_settings
            if session is self
            else session.set_input_channel_settings
        )
        return method(local, settings)
