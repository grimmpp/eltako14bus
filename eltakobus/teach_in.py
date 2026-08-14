"""Eltako sender teach-in telegrams and device associations.

These payloads are Eltako application conventions used when a sender is taught
into a series-14 actuator.  They are intentionally separate from generic
EnOcean teach-in parsing and contain no Home Assistant code.
"""

from __future__ import annotations

from .device_catalog import DEVICE_CATALOG, normalize_hw_type
from .eep import A5_10_06, A5_10_12, A5_38_08, EEP, H5_3F_7F
from .message import Regular4BSMessage


# Sender EEP -> DB3..DB0 payload of the Eltako teach-in telegram.
EEP_WITH_TEACH_IN_BUTTONS = {
    A5_10_06: bytes.fromhex("40 30 0D 85"),
    A5_10_12: bytes.fromhex("40 90 0D 80"),
    A5_38_08: bytes.fromhex("E0 40 0D 80"),
    H5_3F_7F: bytes.fromhex("FF F8 0D 80"),
}


def _resolve(eep) -> type | None:
    """Resolve an EEP class or a name such as ``A5-10-06``."""
    if eep is None:
        return None
    if isinstance(eep, type):
        return eep
    try:
        return EEP.find(str(eep).upper().replace("_", "-"))
    except (KeyError, TypeError, AttributeError):
        return None


def supports_teach_in_button(eep) -> bool:
    """Return whether an Eltako sender has a known button teach-in payload."""
    return _resolve(eep) in EEP_WITH_TEACH_IN_BUTTONS


def get_teach_in_payload(eep) -> bytes | None:
    """Return a copy of the sender's Eltako teach-in payload, if known."""
    payload = EEP_WITH_TEACH_IN_BUTTONS.get(_resolve(eep))
    return bytes(payload) if payload is not None else None


def teach_in_button_eep_names() -> list[str]:
    """Return sender EEP names for which a teach-in button can be created."""
    return sorted(eep.eep_string for eep in EEP_WITH_TEACH_IN_BUTTONS)


def build_teach_in_message(address, eep) -> Regular4BSMessage:
    """Build the outgoing Eltako teach-in telegram for *eep*.

    The status byte ``0x80`` and outgoing flag match the series-14 telegram
    convention used by Eltako actuators.
    """
    payload = get_teach_in_payload(eep)
    if payload is None:
        raise ValueError(f"No Eltako teach-in payload is known for {eep!r}")
    return Regular4BSMessage(address=address, data=payload, outgoing=True, status=0x80)


def teach_in_devices(eep=None) -> tuple[dict, ...]:
    """Return catalog entries whose sender EEP has a known teach-in payload."""
    wanted = _resolve(eep) if eep is not None else None
    result = []
    seen = set()
    for entry in DEVICE_CATALOG:
        sender_eep = _resolve(entry.get("sender_eep"))
        if sender_eep not in EEP_WITH_TEACH_IN_BUTTONS:
            continue
        if wanted is not None and sender_eep is not wanted:
            continue
        key = tuple(sorted(entry.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(entry))
    return tuple(result)


def teach_in_profiles_for_device(hw_type: str) -> tuple[dict, ...]:
    """Return the teach-in-capable sender profiles of one catalog device."""
    normalized = normalize_hw_type(hw_type)
    return tuple(
        entry for entry in teach_in_devices()
        if normalize_hw_type(entry.get("hw_type")) == normalized
    )
