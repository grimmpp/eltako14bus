# Upstream issue triage

This document records which requests from the
[home-assistant-eltako issue tracker](https://github.com/grimmpp/home-assistant-eltako/issues)
belong in this independent protocol library. Eltako-specific wire definitions
take precedence over generic EEP descriptions. The implementation was checked
against the linked [Eltako telegram catalogue](https://www.eltako.com/fileadmin/downloads/de/Gesamtkatalog/Eltako_Gesamtkatalog_KapT_low_res.pdf).
The generic profile definitions and bit offsets were additionally checked
against the [EnOcean Alliance EEP 2.6.7 specification](https://www.enocean-alliance.org/wp-content/uploads/2017/05/EnOcean_Equipment_Profiles_EEP_v2.6.7_public.pdf).

## EEP 2.6.7 validation

The standard 4BS temperature family now exposes the concrete A5-02 profile
classes, including the 10-bit variants A5-02-20 and A5-02-30. The standard
A5-06-03 and A5-07-02 profiles are also implemented. Their DB ordering follows
the EEP convention used by `Regular4BSMessage`: `data[0]` is DB3 and
`data[3]` is DB0.

The A5-06-02, A5-09-05, A5-20-04, and selected A5-14/A5-30 telegrams retain
their Eltako device-specific interpretation where the Eltako catalogue gives
fixed markers or a device-specific status layout. They are not silently
replaced with a generic interpretation, because doing so would break captured
Eltako telegrams and existing callers.

## Added here

| Issue | Decision |
| --- | --- |
| [#199 A5-02-05](https://github.com/grimmpp/home-assistant-eltako/issues/199) | Implemented as `A5_02_05`: pure temperature, 0 to 40 °C according to the official EEP definition, metadata, encode/decode and regression tests. |
| [#174 A5-07-03](https://github.com/grimmpp/home-assistant-eltako/issues/174) | Implemented as `A5_07_03`: occupancy, 0…5 V supply voltage and 10-bit 0…1000 lx illumination. |
| [#183 F6-05-02](https://github.com/grimmpp/home-assistant-eltako/issues/183) | Implemented as `F6_05_02`: raw smoke status, alarm and low-battery state for RPS telegrams. |
| Eltako catalogue profiles | Added/updated `A5_06_02`, `A5_09_05`, `A5_14_09`, `A5_14_0A`, `A5_20_04`, `F6_05_01`, and the Eltako-specific `A5_30_03` alarm layout. |
| [#185 USB300 ESP3 conversion](https://github.com/grimmpp/home-assistant-eltako/issues/185) | The library already has defensive `ESP3MessageAdapter` conversion. Unsupported packets are logged and ignored; conversion tests cover malformed and `WRONG_PARAM` responses. |
| [#118 message delay](https://github.com/grimmpp/home-assistant-eltako/issues/118) | Already covered by `RS485SerialInterfaceV2.delay_message`, benchmark tooling, reconnect tests and hardware-test documentation. |
| [#121 remote serial path](https://github.com/grimmpp/home-assistant-eltako/issues/121) | The library already accepts arbitrary pyserial URLs and provides the ESP2-over-TCP interface. |

## Candidates requiring protocol data first

- [#183 smoke/heat detectors](https://github.com/grimmpp/home-assistant-eltako/issues/183): A5-30-03 is already present. The FRW RPS profile is now covered; FHMB/FRWB-specific A5-30-03 alarm semantics still need captured telegrams.
- [#192 decentralized devices](https://github.com/grimmpp/home-assistant-eltako/issues/192): A5-07-01 and A5-38-08 are partly represented already; F6-05-02 and the requested device-specific behavior need complete EEP definitions and fixtures.
- [#193 FJ62NP teach-in](https://github.com/grimmpp/home-assistant-eltako/issues/193): this concerns application-level teach-in policy and the distinction between A5/H5 commands. A raw message API can support it, but automatic acceptance or aliasing would be unsafe without hardware confirmation.

## Home-Assistant-only

The following remain in `home-assistant-eltako`: cover direction inversion and position persistence ([#209](https://github.com/grimmpp/home-assistant-eltako/issues/209), [#210](https://github.com/grimmpp/home-assistant-eltako/issues/210)), climate entity configuration ([#187](https://github.com/grimmpp/home-assistant-eltako/issues/187), [#189](https://github.com/grimmpp/home-assistant-eltako/issues/189)), HA entity IDs and API deprecations, and sensor units. They do not change ESP2/ESP3 framing or EEP encoding and would introduce an unwanted HA dependency here.
