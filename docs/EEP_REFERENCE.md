# Implemented EEP reference

This page lists every EEP profile currently registered by
`eltakobus.eep.EEP`. The list is based on the runtime registry in
`eep.py` and currently contains 71 profiles. Names use the standard
`RORG-FUNC-TYPE` notation.

The metadata is also available to applications:

```python
from eltakobus.eep import EEP

profile = EEP.find("A5-04-02")
metadata = profile.get_metadata()
print(metadata.name, metadata.org)
for field in metadata.fields:
    print(field.name, field.value_range, field.unit, field.values)
```

`value_range` describes the decoded/encoded physical or logical value exposed
by the Python API, not the raw byte range. `values` contains symbolic values
for enumerations and bit fields. `ORG` is the ESP2/EnOcean organization byte;
`n/a` means that the profile is used for a status representation without a
single outgoing radio organization.

## A5 temperature profiles

| EEP | Name | ORG | Fields and ranges |
|---|---|---:|---|
| A5-02-01 | Temperature sensor | 07 | `current_temperature` −40…0 °C; `profile_marker` 0…255 |
| A5-02-02 | Temperature sensor | 07 | `current_temperature` −30…10 °C; `profile_marker` 0…255 |
| A5-02-03 | Temperature sensor | 07 | `current_temperature` −20…20 °C; `profile_marker` 0…255 |
| A5-02-04 | Temperature sensor | 07 | `current_temperature` −10…30 °C; `profile_marker` 0…255 |
| A5-02-05 | Temperature sensor | 07 | `current_temperature` 0…40 °C; `profile_marker` 0…255 |
| A5-02-06 | Temperature sensor | 07 | `current_temperature` 10…50 °C; `profile_marker` 0…255 |
| A5-02-07 | Temperature sensor | 07 | `current_temperature` 20…60 °C; `profile_marker` 0…255 |
| A5-02-08 | Temperature sensor | 07 | `current_temperature` 30…70 °C; `profile_marker` 0…255 |
| A5-02-09 | Temperature sensor | 07 | `current_temperature` 40…80 °C; `profile_marker` 0…255 |
| A5-02-0A | Temperature sensor | 07 | `current_temperature` 50…90 °C; `profile_marker` 0…255 |
| A5-02-0B | Temperature sensor | 07 | `current_temperature` 60…100 °C; `profile_marker` 0…255 |
| A5-02-10 | Temperature sensor | 07 | `current_temperature` −60…20 °C; `profile_marker` 0…255 |
| A5-02-11 | Temperature sensor | 07 | `current_temperature` −50…30 °C; `profile_marker` 0…255 |
| A5-02-12 | Temperature sensor | 07 | `current_temperature` −40…40 °C; `profile_marker` 0…255 |
| A5-02-13 | Temperature sensor | 07 | `current_temperature` −30…50 °C; `profile_marker` 0…255 |
| A5-02-14 | Temperature sensor | 07 | `current_temperature` −20…60 °C; `profile_marker` 0…255 |
| A5-02-15 | Temperature sensor | 07 | `current_temperature` −10…70 °C; `profile_marker` 0…255 |
| A5-02-16 | Temperature sensor | 07 | `current_temperature` 0…80 °C; `profile_marker` 0…255 |
| A5-02-17 | Temperature sensor | 07 | `current_temperature` 10…90 °C; `profile_marker` 0…255 |
| A5-02-18 | Temperature sensor | 07 | `current_temperature` 20…100 °C; `profile_marker` 0…255 |
| A5-02-19 | Temperature sensor | 07 | `current_temperature` 30…110 °C; `profile_marker` 0…255 |
| A5-02-1A | Temperature sensor | 07 | `current_temperature` 40…120 °C; `profile_marker` 0…255 |
| A5-02-1B | Temperature sensor | 07 | `current_temperature` 50…130 °C; `profile_marker` 0…255 |
| A5-02-20 | 10-bit temperature sensor | 07 | `current_temperature` −10…41.2 °C |
| A5-02-30 | 10-bit temperature sensor | 07 | `current_temperature` −40…62.3 °C |

## A5 sensors and controllers

| EEP | Name | ORG | Fields and ranges |
|---|---|---:|---|
| A5-04-01 | Temperature and humidity sensor | 07 | `current_temperature` 0…40 °C; `humidity` 0…100 %; `temp_availability`, `learn_button` 0…1 |
| A5-04-02 | Temperature and humidity sensor | 07 | `current_temperature` −20…60 °C; `humidity` 0…100 %; `learn_button` 0…1 |
| A5-04-03 | Extended temperature and humidity sensor | 07 | `current_temperature` −20…60 °C; `humidity` 0…100 %; `telegram_type` heartbeat/event; `learn_button` 0…1 |
| A5-06-01 | Brightness and twilight sensor | 07 | `twilight` 0…255 lx; `day_light` 300…30,000 lx; `illumination` 0…30,000 lx |
| A5-06-02 | Light and supply-voltage sensor | 07 | `supply_voltage` 0…5.1 V; `illumination` 0…1,020 lx; `profile_marker` 0…255 |
| A5-06-03 | 10-bit light sensor | 07 | `supply_voltage` 0…5 V; `illumination` 0…1,000 lx; `error_code` 0…255 |
| A5-07-01 | Occupancy sensor | 07 | `support_voltage` 0…5 V; `pir_status` 0…255; `pir_status_on`, `support_volrage_availability`, `learn_button` 0…1 |
| A5-07-02 | Occupancy sensor with supply voltage | 07 | `supply_voltage` 0…5 V; `motion_detected` 0…1; `error_code` 0…255 |
| A5-07-03 | Occupancy and illumination sensor | 07 | `supply_voltage` 0…5 V; `illumination` 0…1,000 lx; `motion_detected` 0…1; `error_code` 0…255 |
| A5-08-01 | Light, temperature and occupancy sensor | 07 | `supply_voltage` 0…5.1 V; `illumination` 0…510 lx; `temperature` 0…51 °C; learn/PIR/occupancy flags 0…1 |
| A5-09-04 | CO₂, temperature and humidity sensor | 07 | `humidity` 0…100 %; `co2` 0…2,550 ppm; `temperature` 0…51 °C; `learn_button` 0…1 |
| A5-09-05 | VOC sensor | 07 | `concentration` 0…500; `profile_marker` 0…255 |
| A5-09-0C | Air quality sensor | 07 | `concentration` 0…167,769.6; `voc_type`; `voc_unit` ppb/µg/m³; `learn_button` 0…1 |
| A5-10-03 | Thermostat | 07 | `target_temperature` 8…30 °C; `current_temperature` 0…40 °C |
| A5-10-06 | Heating and cooling controller | 07 | `mode`; `target_temperature` 0…40 °C; `current_temperature` 0…40 °C; `priority` |
| A5-10-12 | Heating, cooling and humidity controller | 07 | `current_temperature`, `target_temperature`; `humidity` 0…100 % |
| A5-12-01 | Automated meter reading | 07 | `meter_reading` 0…16,777,215; `measurement_channel` 0…15; learn/data/divisor fields |
| A5-12-02 | Automated meter reading | 07 | `meter_reading` 0…16,777,215; `measurement_channel` 0…15; learn/data/divisor fields |
| A5-12-03 | Automated meter reading | 07 | `meter_reading` 0…16,777,215; `measurement_channel` 0…15; learn/data/divisor fields |
| A5-13-01 | Weather station | 07 | `identifier` weather/sun position; `dawn_sensor` 0…999; `wind_speed` 0…70 m/s; day/night/rain flags; sun directions 0…150 klx; `temperature`; `hemisphere` |
| A5-13-02 | Sun-position sensor | 07 | `sun_west`, `sun_south`, `sun_east` 0…150 klx; `hemisphere`, `learn_button` 0…1 |
| A5-13-04 | Time and weekday | 07 | `weekday` 1…7; `hour` 0…23 h; `minute`, `second` 0…59; 12/24-hour and AM/PM flags |
| A5-14-01 | Contact sensor | 07 | `supply_voltage` 0…5 V; `contact` 0…1; `learn_button`; `error_code` 0…255 |
| A5-14-03 | Contact and vibration sensor | 07 | `supply_voltage` 0…5 V; `contact`, `vibration`, `learn_button` 0…1; `error_code` |
| A5-14-05 | Vibration sensor | 07 | `supply_voltage` 0…5 V; `vibration`, `learn_button` 0…1; `error_code` |
| A5-14-07 | Door and lock contact | 07 | `supply_voltage` 0…5 V; `door_contact`, `lock_contact`, `learn_button` 0…1; `error_code` |
| A5-14-08 | Door, lock and vibration sensor | 07 | `supply_voltage` 0…5 V; `door_contact`, `lock_contact`, `vibration`, `learn_button` 0…1; `error_code` |
| A5-14-09 | Window contact | 07 | `supply_voltage` 0…5 V; `window_state` closed/tilted/open; `alarm` 0…1 |
| A5-14-0A | Window contact | 07 | `supply_voltage` 0…5 V; `window_state` closed/tilted/open; `alarm` 0…1 |
| A5-20-04 | Valve and temperature sensor | 07 | `valve_position` 0…100 %; `temperature`; `status` 0…255; `battery_empty` 0…1 |
| A5-30-01 | Digital input with battery status | 07 | battery/contact raw statuses 0…255; `low_battery`, `contact_closed`, `learn_button` 0…1 |
| A5-30-03 | Four digital inputs and temperature | 07 | `temperature` 0…40 °C; `alarm_status`, `profile_marker` 0…255; `alarm` 0…1 |
| A5-38-08 | Central command | 07 | `command` 1=switching, 2=dimming; switching includes time, delay/duration and `lock`; dimming includes value, ramping and store-final-value |

## D5 and F6 contact/switch profiles

| EEP | Name | ORG | Fields and ranges |
|---|---|---:|---|
| D5-00-01 | Single input contact | 06 | `learn_button`, `contact` 0…1 |
| F6-01-01 | One-button switch | 05 | `button_pushed` 0…1 |
| F6-02-01 | Two-rocker switch, application style 1 | 05 | rocker actions 0…7; energy/second-action flags 0…1 |
| F6-02-02 | Two-rocker switch, application style 2 | 05 | rocker actions 0…7; energy/second-action flags 0…1 |
| F6-05-01 | Water leakage detector | 05 | `status` 0…255; `water_detected` 0…1 |
| F6-05-02 | Smoke detector | 05 | `status` 0…255; `smoke_alarm`, `low_battery` 0…1 |
| F6-10-00 | Window handle | 05 | `movement` 0…15; `handle_position`: closed/open/tilt |

## G5, H5 and M5 actuator profiles

| EEP | Name | ORG | Fields and ranges |
|---|---|---:|---|
| G5-3F-7F | Shutter status | n/a | `state` 0…255; `time` 0…65,535 s; `direction` 0…255 |
| H5-3F-7F | Shutter command | 07 | `time` 0…6,553.5 s; `command` 0…255; `learn_button`, `send_time_in_seconds` 0…1 |
| M5-38-08 | Eltako switching command | 05 | `state` 0…1 |

## D2 VLD profiles

These profiles are decoded from ESP3 VLD telegrams. They accept the public
`VLDMessage` object or any incoming message exposing compatible `org` and
`data` attributes; they cannot be represented as the fixed four-byte ESP2
message. Reserved and error encodings are retained in `*_raw` attributes and
the corresponding physical property is returned as `None`.

| EEP | Name | ORG | Fields and ranges |
|---|---|---:|---|
| D2-00-01 | RCP with temperature measurement and display | D2 | handle/window/button/alarm state; `temperature` −20…60 °C; `humidity` 0…100 %; `illumination` 0…60,000 lx; `battery_state` 0…100 % |
| D2-14-40 | Indoor multisensor | D2 | `temperature` −40…60 °C; `humidity` 0…100 %; `illumination` 0…100,000 lx; three-axis acceleration −2.5…2.5 g |
| D2-14-41 | Indoor multisensor with contact | D2 | D2-14-40 fields plus `contact` 0…1 |

D2-14-40 is marked as a draft proposal in the current EEP Viewer material;
applications should therefore keep the raw values and tolerate future profile
revisions.

## Notes on interpretation

For A5-38-08 switching commands, `lock=True` tells the addressed actuator to
ignore all commands until the timer expires. A timer of `0` creates an
unlimited lock. Only an explicit unlock command is accepted during the lock
phase; this is an actuator command lock, not a cryptographic or installation
security feature.

Some fields are intentionally exposed as raw status or marker values because
their meaning depends on Eltako device configuration. For example, meter
`divisor`, alarm markers, controller modes, and actuator command codes should
not be converted to a universal unit without considering the device manual.
The Python class remains authoritative for encoding and decoding; this page is
the human-readable index of the declared metadata.

To verify that the documented registry remains complete, run:

```sh
python -m unittest tests.generic_eep_test tests.eep_validation_test tests.eltako_eep_test -v
```
