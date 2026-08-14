# Device catalog

`eltakobus.device_catalog` contains the device and EEP mapping used by
diagnostic, discovery, and configuration tools. It has no Home Assistant
dependency and does not open a serial interface.

```python
from eltakobus.device_catalog import (
    describe_hw_type,
    devices_for_eep,
    find_hw_type,
)

device = find_hw_type("FSR14-4x")
print(device["eep"])             # M5-38-08
print(device["address_count"])   # 4

for entry in devices_for_eep("A5-10-06"):
    print(entry["hw_type"], entry["description"])
```

The catalog distinguishes the EEP used for received device telegrams (`eep`)
from the EEP used for outgoing commands (`sender_eep`). Use
`devices_for_eep(name, include_sender=True)` when both directions are needed.
`eep_device_mapping()` returns the complete reverse index.

The initial device mapping was compared with the catalog used by the
[home-assistant-eltako integration](https://github.com/grimmpp/home-assistant-eltako/tree/version2.2/custom_components/eltako/catalog)
as an external reference. That repository is not imported, installed, or required
at runtime; this package owns the copied data and its lookup logic independently.
