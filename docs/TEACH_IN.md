# Eltako teach-in support

`eltakobus.teach_in` contains the Eltako-specific sender teach-in payloads
used by series-14 actuators. It is independent of Home Assistant and can be
used by command-line tools, simulations, or other integrations.

```python
from eltakobus.teach_in import (
    build_teach_in_message,
    teach_in_profiles_for_device,
)

message = build_teach_in_message(bytes.fromhex("01020304"), "A5-38-08")
print(message.data.hex())       # e0400d80
print(teach_in_profiles_for_device("FSB14"))
```

Currently the catalog provides the documented Eltako teach-in payloads for
`A5-10-06`, `A5-10-12`, `A5-38-08`, and `H5-3F-7F`. The helper refuses unknown
profiles instead of guessing a payload. Generic EnOcean teach-in telegrams
remain separate and are handled by the existing message/profile code.
