"""Stable controller-owned references used by temperature consumers."""

from dataclasses import dataclass

CONTROLLER_IDS = ("primary", "secondary")


def controller_id(value):
    """Validate a persistent controller slot without interpreting display labels."""
    if value not in CONTROLLER_IDS:
        raise ValueError(f"Unknown temperature controller: {value!r}")
    return value


@dataclass(frozen=True, order=True)
class LoopRef:
    """Identify a local loop on a stable controller slot."""

    controller_id: str
    loop: int

    def __post_init__(self):
        controller_id(self.controller_id)
        if type(self.loop) is not int or self.loop < 1:
            raise ValueError("A temperature loop must be a positive integer.")

    def __str__(self):
        return f"{self.controller_id.title()} / Loop {self.loop}"

    def to_json(self):
        """Return the persistent reference, independent of connection order."""
        return {"controller_id": self.controller_id, "loop": self.loop}


@dataclass(frozen=True, order=True)
class ChannelRef:
    """Identify a native sensor channel on a stable controller slot."""

    controller_id: str
    channel: str

    def __post_init__(self):
        controller_id(self.controller_id)
        if not isinstance(self.channel, str) or not self.channel.strip():
            raise ValueError("A temperature channel must have a non-empty name.")

    def __str__(self):
        return f"{self.controller_id.title()} / {self.channel}"

    def to_json(self):
        """Return a JSON-compatible sensor reference."""
        return {"controller_id": self.controller_id, "channel": self.channel}


def loop_ref(value, default="primary"):
    """Read a qualified reference or a legacy local loop number."""
    if isinstance(value, LoopRef):
        return value
    if isinstance(value, dict):
        return LoopRef(value["controller_id"], value["loop"])
    return LoopRef(default, value)


def channel_ref(value, default="primary"):
    """Read a qualified reference or a legacy local sensor name."""
    if isinstance(value, ChannelRef):
        return value
    if isinstance(value, dict):
        return ChannelRef(value["controller_id"], value["channel"])
    return ChannelRef(default, value)


def reference_json(value):
    """Preserve legacy values and serialise qualified selections."""
    return value.to_json() if isinstance(value, (LoopRef, ChannelRef)) else value
