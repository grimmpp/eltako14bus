# D2 EEP migration for v2

## Why this correction is necessary

Versions up to 1.0.1 registered a class named `D2_00_01` whose payload fields
were burglary/protection alarms, window-handle and window state, buttons,
motion, vacation mode, temperature, humidity, illumination and battery state.
Those fields belong to EnOcean EEP D2-06-01, not D2-00-01.

D2-00-01 is a bidirectional room-control-panel profile. Its first byte carries
a three-bit message ID at bit offset 5. The five defined variants are:

| ID | Type | Direction | Content |
|---:|:---:|---|---|
| 1 | A | sensor to gateway | first user action and configuration validity |
| 2 | B | gateway to sensor | display content |
| 3 | C | sensor to gateway | repeated user action and set-point adjustment |
| 4 | D | sensor to gateway | temperature measurement result |
| 5 | E | gateway to sensor | sensor configuration |

The v2 decoder follows the corrected little-endian value order documented in
EEP 2.6.8. Unsupported message IDs raise `eltakobus.error.NotImplementedError`
with the rejected ID; short or malformed variants raise `ValueError`.

## Updating existing code

Code that intentionally decodes the window-handle/multisensor payload should
change its profile name and class import:

```python
from eltakobus.eep import D2_06_01, EEP

profile = EEP.find("D2-06-01")
values = D2_06_01.decode_message(message)
print(values.handle_position, values.temperature)
```

For a temporary, explicit compatibility path, the same decoder is available
as `D2_00_01_LegacyWindowHandle`. The alias is deliberately not registered as
an EEP because its old identifier was incorrect:

```python
from eltakobus.eep import D2_00_01_LegacyWindowHandle

legacy_values = D2_00_01_LegacyWindowHandle.decode_message(message)
```

Code using actual room-control-panel telegrams should continue to resolve
`EEP.find("D2-00-01")`, but will now receive message-specific attributes such
as `message_id`, `message_type`, `config_valid`, `user_action`, `setpoint` or
`measurement` instead of window-sensor attributes.

## Device catalog behavior

`find_hw_type()` returns the first catalog row and therefore the factory
profile `D2-14-41` for FMMS44SB, FMS55SB, FMS55ESB and FMS65ESB.
`entries_for_hw_type()` returns the additional NFC-selectable D2 profiles.
D2-00-01 is offered only for FMMS44SB.

## Current limitations

- D2-06-01 currently decodes the migrated sensor-values message type `0x00`;
  its configuration and log/report variants are not part of this bounded slice.
- The D2-00-01 decoder parses message variants A through E but does not send them.
- Smart Ack response timing, message chaining and transaction matching are not
  handled by an EEP decoder.
- Display values whose unit depends on `figure_type` retain
  `figure_value_raw`; `figure_value` is scaled only for the documented
  hundredth-degree and percentage-style variants.
- Reserved physical values remain available in their `*_raw` attributes and
  are exposed as `None` where interpreting them as a measurement would be
  misleading.

## Sources

- [EnOcean Equipment Profiles 2.6.8](https://www.enocean-alliance.org/wp-content/uploads/2019/10/EEP268_R3_Feb022018_public.pdf),
  profiles D2-00-01 and D2-06-01
- [Eltako FMMS44SB data sheet](https://www.eltako.com/fileadmin/downloads/en/_datasheets/Datasheet_FMMS44SB.pdf)
- Eltako catalogue chapter “Radio telegram contents” for the profile choices of
  FMMS44SB, FMS55SB, FMS55ESB and FMS65ESB
