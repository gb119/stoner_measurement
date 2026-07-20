"""MKS mass-flow and pressure-flow controller drivers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from stoner_measurement.instruments.mass_flow_controller import (
    MassFlowController,
    MassFlowControllerCapabilities,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.mks import MKSPR4000Protocol, MKSPSRProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

_PSR_VALUE_INDEX_RE = re.compile(r"^P(\d{2})$", re.IGNORECASE)
_PSR_NUMERIC_TOKEN_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class _PSRChannelPorts:
    """Port mapping for one logical PSR channel."""

    pv_port: str
    sp_port: str


class MKSPR4000BS(MassFlowController):
    """Driver for the MKS PR4000B-S single-channel controller."""

    DISPLAY_NAME = "MKS PR4000B-S"

    _UNIT_NAMES = {
        0: "ubar",
        1: "mbar",
        2: "bar",
        3: "mTorr",
        4: "Torr",
        5: "kTorr",
        6: "Pa",
        7: "kPa",
        8: "mH2O",
        9: "cH2O",
        10: "PSI",
        11: "N/qm",
        12: "SCCM/CC",
        13: "SLM/L",
        14: "SCM/CM",
        15: "SCFH/CF",
        17: "mA",
        18: "V",
        19: "%",
        20: "C",
    }

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
    ) -> None:
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else MKSPR4000Protocol(),
        )

    def identify(self) -> str:
        """Return a static identifier for the PR4000B-S family."""
        return "MKS PR4000B-S"

    def reset(self) -> None:
        """Do not expose the PR4000B-S defaults reset via the generic API."""
        raise NotImplementedError(
            "PR4000B-S reset-to-default is intentionally not exposed via reset()."
        )

    def get_capabilities(self) -> MassFlowControllerCapabilities:
        return MassFlowControllerCapabilities(
            channel_count=1,
            supports_unit_control=True,
            supports_range_control=True,
            supports_valve_control=True,
            supports_pressure_control=True,
        )

    def read_actual_value(self, channel: int = 1) -> float:
        self.validate_channel(channel)
        return self._query_float("$")

    def read_setpoint(self, channel: int = 1) -> float:
        self.validate_channel(channel)
        return self._query_float("`")

    def set_setpoint(self, value: float, channel: int = 1) -> None:
        self.validate_channel(channel)
        self._send_ack(f"@{self._format_float(value)}")

    def read_unit(self, channel: int = 1) -> int:
        self.validate_channel(channel)
        return self._query_int("c")

    def set_unit(self, unit_code: int | str, channel: int = 1) -> None:
        self.validate_channel(channel)
        self._send_ack(f"C{self._format_byte(int(unit_code))}")

    def read_range(self, channel: int = 1) -> float:
        self.validate_channel(channel)
        return self._query_float("b")

    def set_range(self, full_scale: float, channel: int = 1) -> None:
        self.validate_channel(channel)
        self._send_ack(f"B{self._format_float(full_scale)}")

    def valve_enabled(self, channel: int = 1) -> bool:
        self.validate_channel(channel)
        return bool(self._query_int("a"))

    def set_valve_enabled(self, enabled: bool, channel: int = 1) -> None:
        self.validate_channel(channel)
        self._send_ack(f"A{self._format_byte(1 if enabled else 0)}")

    def read_status1(self) -> int:
        return self._query_int("&")

    def read_status2(self) -> int:
        return self._query_int("'")

    def read_status3(self) -> int:
        return self._query_int("(")

    def read_status4(self) -> int:
        return self._query_int(")")

    def read_status_bytes(self) -> tuple[int, int, int, int]:
        """Return all four PR4000B-S status bytes."""
        return (
            self.read_status1(),
            self.read_status2(),
            self.read_status3(),
            self.read_status4(),
        )

    def read_unit_name(self, channel: int = 1) -> str:
        """Return a friendly name for the configured engineering unit."""
        code = self.read_unit(channel=channel)
        return self._UNIT_NAMES.get(code, f"unknown({code})")

    def _send_ack(self, command: str) -> None:
        self.query(command)

    def _query_float(self, command: str) -> float:
        reply = self.query(command).strip()
        try:
            return float(reply)
        except ValueError as exc:
            raise ValueError(f"Invalid PR4000B-S numeric reply for {command!r}: {reply!r}") from exc

    def _query_int(self, command: str) -> int:
        reply = self.query(command).strip()
        try:
            return int(reply)
        except ValueError as exc:
            raise ValueError(f"Invalid PR4000B-S integer reply for {command!r}: {reply!r}") from exc

    @staticmethod
    def _format_byte(value: int) -> str:
        return f"{value:03d}"

    @staticmethod
    def _format_float(value: float) -> str:
        return f"{value:+0.5f}"


class _MKSPSRBase(MassFlowController):
    """Shared implementation for the MKS PSR controller family."""

    DISPLAY_NAME = "MKS PSR"
    CHANNEL_PORTS: dict[int, _PSRChannelPorts] = {1: _PSRChannelPorts("01", "02")}

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
        *,
        network_address: str | None = None,
        decimal_places: dict[int, int] | None = None,
    ) -> None:
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else MKSPSRProtocol(),
        )
        self._network_address = network_address
        self._decimal_places = decimal_places or {}

    def identify(self) -> str:
        """Return a static identifier for the PSR family variant."""
        return self.DISPLAY_NAME

    @staticmethod
    def parse_identity_response(response: str) -> dict[str, str]:
        """Parse a PSR identity reply into named fields.

        The manual excerpt confirmed by the user shows responses in the form::

            AZ,32596,4,MKS Instruments,Model PSR1A,02,21.09.03,EE00,5C

        Returns a dict containing the most useful high-level fields. Unknown
        or missing fields are returned as empty strings.
        """
        tokens = [token.strip() for token in response.split(",")]
        model_field = tokens[4] if len(tokens) > 4 else ""
        model = model_field.replace("Model", "", 1).strip() if model_field else ""
        return {
            "preamble": tokens[0] if len(tokens) > 0 else "",
            "network_address": tokens[1] if len(tokens) > 1 else "",
            "response_type": tokens[2] if len(tokens) > 2 else "",
            "manufacturer": tokens[3] if len(tokens) > 3 else "",
            "model": model,
            "model_field": model_field,
            "firmware_major": tokens[5] if len(tokens) > 5 else "",
            "firmware_version": tokens[6] if len(tokens) > 6 else "",
            "build_code": tokens[7] if len(tokens) > 7 else "",
            "checksum": tokens[8] if len(tokens) > 8 else "",
        }

    def reset(self) -> None:
        """PSR reset semantics are not standardised across firmware builds."""
        raise NotImplementedError("PSR reset is not exposed via the generic reset() API.")

    def synchronize(self) -> None:
        """Reset the PSR command state machine."""
        self.write("\x1bAZ")

    def menu(self) -> str:
        """Return the PSR utility menu text."""
        return self.query(self._frame("M"))

    def read_actual_value(self, channel: int = 1) -> float:
        self.validate_channel(channel)
        ports = self._ports_for_channel(channel)
        response = self.query(self._frame("K", port=ports.pv_port))
        return self._parse_measured_value(response)

    def read_setpoint(self, channel: int = 1) -> float:
        self.validate_channel(channel)
        raw = self.get_parameter(self._ports_for_channel(channel).sp_port, 1)
        return self._decode_scaled(raw, channel)

    def set_setpoint(self, value: float, channel: int = 1) -> None:
        self.validate_channel(channel)
        self.set_parameter(
            self._ports_for_channel(channel).sp_port,
            1,
            self._encode_scaled(value, channel),
        )

    def read_unit(self, channel: int = 1) -> int:
        self.validate_channel(channel)
        raw = self.get_parameter(self._ports_for_channel(channel).pv_port, 4)
        return int(raw)

    def set_unit(self, unit_code: int | str, channel: int = 1) -> None:
        self.validate_channel(channel)
        self.set_parameter(self._ports_for_channel(channel).pv_port, 4, str(unit_code))

    def read_range(self, channel: int = 1) -> float:
        self.validate_channel(channel)
        raw = self.get_parameter(self._ports_for_channel(channel).pv_port, 9)
        return self._decode_scaled(raw, channel)

    def set_range(self, full_scale: float, channel: int = 1) -> None:
        self.validate_channel(channel)
        encoded = self._encode_scaled(full_scale, channel)
        ports = self._ports_for_channel(channel)
        self.set_parameter(ports.pv_port, 9, encoded)
        self.set_parameter(ports.sp_port, 9, encoded)

    def get_parameter(self, port: str, index: int) -> str:
        """Return the raw value for one PSR parameter.

        Notes:
            The exact single-parameter read syntax is not shown clearly in the
            manual extraction used for this repository. This implementation
            assumes the instrument accepts ``Pzz`` as a query selector on the
            addressed port and returns a structured ``...,Pzz,<value>,...`` reply.
        """
        response = self.query(self._frame(f"P{index:02d}", port=port))
        return self._extract_parameter_value(response, index)

    def set_parameter(self, port: str, index: int, value: str) -> None:
        """Write one PSR parameter and validate the echoed reply."""
        response = self.query(self._frame(f"P{index:02d}={value}", port=port))
        echoed = self._extract_parameter_value(response, index)
        if echoed != value:
            raise ValueError(
                f"PSR parameter echo mismatch for port {port} index {index:02d}: "
                f"wrote {value!r}, got {echoed!r}."
            )

    def configure_mfc_channel(
        self,
        channel: int,
        *,
        full_scale: float,
        units_code: int = 18,
        time_base_code: int = 2,
        pv_signal_type: str = ";",
        sp_signal_type: int = 5,
        function_code: int = 1,
        valve_override_code: int = 0,
    ) -> None:
        """Configure one channel for a standard analog MFC."""
        self.validate_channel(channel)
        ports = self._ports_for_channel(channel)
        encoded_fs = self._encode_scaled(full_scale, channel)
        self.set_parameter(ports.pv_port, 0, pv_signal_type)
        self.set_parameter(ports.pv_port, 4, str(units_code))
        self.set_parameter(ports.pv_port, 9, encoded_fs)
        self.set_parameter(ports.pv_port, 10, str(time_base_code))
        self.set_parameter(ports.sp_port, 0, str(sp_signal_type))
        self.set_parameter(ports.sp_port, 2, str(function_code))
        self.set_parameter(ports.sp_port, 9, encoded_fs)
        self.set_parameter(ports.sp_port, 29, str(valve_override_code))

    def configure_batch(self, channel: int, rate: float, quantity: float) -> None:
        self.validate_channel(channel)
        caps = self.get_capabilities()
        if not caps.supports_batch:
            super().configure_batch(channel, rate, quantity)
        ports = self._ports_for_channel(channel)
        self.set_parameter(ports.sp_port, 2, "2")
        self.set_parameter(ports.sp_port, 1, self._encode_scaled(rate, channel))
        self.set_parameter(ports.sp_port, 3, self._encode_scaled(quantity, channel))

    def configure_blend(self, master: int, slave: int, ratio_percent: float) -> None:
        caps = self.get_capabilities()
        if not caps.supports_blend:
            super().configure_blend(master, slave, ratio_percent)
        self.validate_channel(master)
        self.validate_channel(slave)
        master_ports = self._ports_for_channel(master)
        slave_ports = self._ports_for_channel(slave)
        self.set_parameter(master_ports.sp_port, 2, "1")
        self.set_parameter(slave_ports.sp_port, 2, "3")
        self.set_parameter(slave_ports.sp_port, 30, self._encode_scaled(ratio_percent, slave))

    def _frame(self, argument: str, *, port: str | None = None) -> str:
        address = self._network_address or ""
        if port is None:
            return f"AZ{address}{argument}"
        return f"AZ{address}.{port}{argument}"

    def _ports_for_channel(self, channel: int) -> _PSRChannelPorts:
        self.validate_channel(channel)
        return self.CHANNEL_PORTS[channel]

    def _decimal_places_for_channel(self, channel: int) -> int:
        self.validate_channel(channel)
        return self._decimal_places.get(channel, 2)

    def _encode_scaled(self, value: float, channel: int) -> str:
        scale = 10 ** self._decimal_places_for_channel(channel)
        return str(int(round(value * scale)))

    def _decode_scaled(self, raw: str, channel: int) -> float:
        scale = 10 ** self._decimal_places_for_channel(channel)
        return int(raw) / scale

    @staticmethod
    def _extract_parameter_value(response: str, expected_index: int) -> str:
        tokens = [token.strip() for token in response.split(",") if token.strip()]
        for pos, token in enumerate(tokens):
            match = _PSR_VALUE_INDEX_RE.match(token)
            if not match:
                continue
            if int(match.group(1)) != expected_index:
                continue
            if pos + 1 >= len(tokens):
                break
            return tokens[pos + 1]
        stripped = response.strip()
        if stripped:
            return stripped
        raise ValueError(
            f"Could not extract PSR parameter value for index {expected_index:02d} "
            f"from response {response!r}."
        )

    @staticmethod
    def _parse_measured_value(response: str) -> float:
        tokens = [token.strip() for token in response.split(",") if token.strip()]
        for pos, token in enumerate(tokens):
            if token.upper() != "K":
                continue
            if pos + 1 < len(tokens):
                return float(tokens[pos + 1])
        numeric_tokens = [token for token in tokens if _PSR_NUMERIC_TOKEN_RE.fullmatch(token)]
        if numeric_tokens:
            return float(numeric_tokens[-1])
        for token in reversed(tokens):
            match = _PSR_NUMERIC_TOKEN_RE.search(token)
            if match:
                return float(match.group(0))
        raise ValueError(f"Could not parse PSR measured-value response: {response!r}")


class MKSPSR1A(_MKSPSRBase):
    """Driver for the MKS PSR1A single-channel controller."""

    DISPLAY_NAME = "MKS PSR1A"
    CHANNEL_PORTS = {1: _PSRChannelPorts("01", "02")}

    def get_capabilities(self) -> MassFlowControllerCapabilities:
        return MassFlowControllerCapabilities(
            channel_count=1,
            supports_unit_control=True,
            supports_range_control=True,
            supports_pressure_control=True,
            supports_batch=True,
            supports_blend=False,
        )


class MKSPSR4A(_MKSPSRBase):
    """Driver for the MKS PSR4A four-channel controller."""

    DISPLAY_NAME = "MKS PSR4A"
    CHANNEL_PORTS = {
        1: _PSRChannelPorts("01", "02"),
        2: _PSRChannelPorts("03", "04"),
        3: _PSRChannelPorts("05", "06"),
        4: _PSRChannelPorts("07", "08"),
    }

    def get_capabilities(self) -> MassFlowControllerCapabilities:
        return MassFlowControllerCapabilities(
            channel_count=4,
            supports_unit_control=True,
            supports_range_control=True,
            supports_pressure_control=True,
            supports_batch=True,
            supports_blend=True,
        )
