# Device catalog

`eltakobus.device_catalog` contains the device and EEP mapping used by
diagnostic, discovery, and configuration tools. It has no Home Assistant
dependency and does not open a serial interface.

```python
from eltakobus.device_catalog import (
    describe_hw_type,
    devices_for_eep,
    entries_for_hw_type,
    find_hw_type,
)

device = find_hw_type("FSR14-4x")
print(device["eep"])             # M5-38-08
print(device["address_count"])   # 4

for entry in devices_for_eep("A5-10-06"):
    print(entry["hw_type"], entry["description"])

# The first row is the factory default; later rows are selectable profiles.
for entry in entries_for_hw_type("FMMS44SB"):
    print(entry["eep"], entry["description"])
```

The catalog distinguishes the EEP used for received device telegrams (`eep`)
from the EEP used for outgoing commands (`sender_eep`). Use
`devices_for_eep(name, include_sender=True)` when both directions are needed.
`eep_device_mapping()` returns the complete reverse index.

The FMMS44SB and FMS55/FMS65 multisensors use `D2-14-41` in their factory
configuration. Their D2 profiles selectable through NFC are represented as
additional rows, so `find_hw_type()` returns the factory default while
`entries_for_hw_type()` exposes the alternatives. D2-00-01 is listed only for
FMMS44SB, in line with the Eltako radio-telegram documentation.

For command-level applicability, see the [A5-38-08 command guide](A5_38_08_COMMANDS.md).
An actuator entry's `sender_eep` identifies the normal command profile; it does
not imply that every optional command variant of that EEP is supported by every
firmware version.

For gateway hardware, protocol and transport selection, see the
[gateway overview](GATEWAYS.md). The catalog identifies hardware families;
the overview documents which transport classes are implemented for each one.

The initial device mapping was compared with the catalog used by the
[home-assistant-eltako integration](https://github.com/grimmpp/home-assistant-eltako/tree/version2.2/custom_components/eltako/catalog)
as an external reference. That repository is not imported, installed, or required
at runtime; this package owns the copied data and its lookup logic independently.
