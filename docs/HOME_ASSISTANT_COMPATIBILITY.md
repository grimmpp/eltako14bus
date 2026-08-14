# Home Assistant integration compatibility

The library-side API used by the
[home-assistant-eltako integration](https://github.com/grimmpp/home-assistant-eltako/tree/version2.2)
is covered by [tests/home_assistant_compatibility_test.py](../tests/home_assistant_compatibility_test.py).

The compatibility surface currently includes:

- all EEP classes imported by the integration;
- stable `.eep_string` identifiers and `EEP.find()` lookup;
- sensor constructors and public properties used by the entities;
- `HeaterMode`, `ControllerPriority`, `VOC_SubstancesType`, and
  `WindowHandlePosition`;
- outgoing switch, dimmer, climate, cover, and gateway telegrams.

The check is deliberately independent of Home Assistant. It tests the library
contract without importing HA or opening hardware.

`A5-09-0C` is used by the integration as a receive/decode profile. Its encoder
is intentionally not implemented because the profile is a measurement telegram
and the integration does not send it. This is not considered a compatibility
failure.
