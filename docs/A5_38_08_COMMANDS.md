# A5-38-08 Central Command

`A5-38-08` is a 4BS gateway-to-actuator profile for switching actuators,
dimmers, HVAC controllers, fans and blinds. It is a command profile, not a
guaranteed status profile; feedback must be decoded with the actuator's own
status EEP.

The library uses regular 4BS ordering: `data[0]` is DB3 and `data[3]` is DB0.
Every outgoing message has ORG `0x07`.

## Which actuators use which commands?

The EEP defines the wire format, but it does not mean that every actuator
implements every command. The following mapping is the practical mapping for
the actor families represented in this repository:

| Actor family | Typical function | A5-38-08 commands | Recommended sender EEP |
|---|---|---|---|
| FSR14, FSR14M, FSR61, FSR71 relay actors | Switching output | `0x01` switching; `lock` only when explicitly required | A5-38-08 |
| F4SR14-LED and similar LED relay actors | Switching output | `0x01` switching | A5-38-08 |
| FUD14, FUD14-800W, FUD61NP/NPN, FUD71 dimmers | Dimming output | `0x01` on/off and `0x02` dimming | A5-38-08 |
| FSG14 1–10 V and FDG/FD2G DALI gateways | Dimming/control output | Usually `0x01` and `0x02`; configuration determines extended behavior | A5-38-08 |
| FSB14, FSB61, FSB71 shutter actors | Blind/shutter movement | Normally `H5-3F-7F`, not A5-38-08 command `0x07` | H5-3F-7F |
| F4HK14, FUTH and similar HVAC actors | Heating/cooling control | Normally `A5-10-06` or `A5-10-12`; A5-38-08 `0x03`–`0x06` only if documented | Device-specific HVAC EEP |
| PEHA/infratec blind controllers | Central blind command | `0x07`, including position, angle, service and status flags | A5-38-08 |
| Generic Thermokon/EnOcean HVAC controllers | Controller/setpoint | `0x03`–`0x06` where supported by the product | A5-38-08 |

The first four rows are the relevant Eltako Series-14 use cases. Commands
`0x03`–`0x07` are standardized variants, but are not automatically available
on every Eltako relay or dimmer. Check the actuator manual, firmware version
and teach-in profile before sending an extended command.

### Practical selection rules

1. Use `0x01` for a relay on/off operation.
2. Use `0x01` for dimmer on/off and `0x02` for an explicit dimming value.
3. Do not use `lock=1` for ordinary light commands. It blocks other commands
   until unlocked and is an operational override, not a requirement for
   FSR14/FUD14 communication.
4. Use `H5-3F-7F` for the Series-14 FSB shutter command path unless the device
   documentation explicitly states that it accepts A5-38-08 command `0x07`.
5. Use the actor's documented HVAC EEP for FUTH/F4HK14 instead of assuming
   that generic A5-38-08 HVAC commands are implemented.

## Command overview

| Command | Function | Main data | DB0 flags |
|---:|---|---|---|
| `0x01` | Switching | DB2+DB1: time in 0.1 s | LRN, lock, delay/duration, on/off |
| `0x02` | Dimming | DB2: value, DB1: ramping seconds | LRN, absolute/relative, store value, on/off |
| `0x03` | Setpoint shift | DB1: −12.7…12.8 K | LRN |
| `0x04` | Basic setpoint | DB1: 0…51.2 °C in 0.2 °C steps | LRN |
| `0x05` | Control variable | DB1: 0…100 % | mode, state, LRN, energy hold-off, occupancy |
| `0x06` | Fan stage | DB1: 0…3 or `255` automatic | LRN |
| `0x07` | Blind/shutter | DB2/DB1: function parameters | function, LRN, status, position/angle, service |

## Creating and sending a command

```python
from eltakobus.eep import A5_38_08, CentralCommandSwitching

address = bytes.fromhex("FF DD CC BB")
command = A5_38_08(
    command=0x01,
    switching=CentralCommandSwitching(
        time=0, learn_button=1, lock=0,
        delay_or_duration=0, switching_command=1,
    ),
)
message = command.encode_message(address)
assert message.data == bytes.fromhex("01 00 00 09")
await bus.send(message)
```

For normal on/off operation use `lock=0`. The lock is an explicit actuator
operation and must not be enabled automatically by a light integration.

## Command 0x01: switching

`time` is encoded in 0.1-second units. `time=0` means no timer.
`delay_or_duration=0` means switch immediately and switch back after the
timer; `delay_or_duration=1` means execute the switch after the delay.

```python
on = A5_38_08(1, switching=CentralCommandSwitching(0, 1, 0, 0, 1))
off = A5_38_08(1, switching=CentralCommandSwitching(0, 1, 0, 0, 0))
locked_on = A5_38_08(1, switching=CentralCommandSwitching(0, 1, 1, 0, 1))

assert on.encode_message(address).data == bytes.fromhex("01 00 00 09")
assert off.encode_message(address).data == bytes.fromhex("01 00 00 08")
assert locked_on.encode_message(address).data == bytes.fromhex("01 00 00 0D")
```

Lock semantics:

- `lock=0` unlocks or leaves the actuator unlocked;
- `lock=1` locks the actuator for `time` when `time > 0`;
- `lock=1` and `time=0` creates an unlimited lock;
- during the lock phase, only an unlock command is accepted.

The lock is not encryption and does not protect the radio telegram. It blocks
other actuator commands, especially commands from taught-in pushbuttons.

## Command 0x02: dimming

`dimming_value` is the absolute value (`0…255`) or relative value (`0…100`),
depending on `dimming_range`. `ramping_time` is expressed in seconds.

```python
from eltakobus.eep import A5_38_08, CentralCommandDimming

command = A5_38_08(2, dimming=CentralCommandDimming(
    dimming_value=128, ramping_time=5, learn_button=1,
    dimming_range=0, store_final_value=1, switching_command=1,
))
message = command.encode_message(address)
```

## Command 0x03 and 0x04: temperature setpoints

```python
shift = A5_38_08(3, setpoint_shift=1.5, learn_button=1)
basic = A5_38_08(4, basic_setpoint=20.0, learn_button=1)
```

Command `0x03` sends a relative shift from `-12.7` to `+12.8 K`.
Command `0x04` sends an absolute basic setpoint from `0` to `51.2 °C` in
`0.2 °C` steps.

## Command 0x05: control variable

```python
from eltakobus.eep import A5_38_08, CentralCommandControlVariable

control = CentralCommandControlVariable(
    control_variable=50.0,
    controller_mode=1,  # 0 automatic, 1 heating, 2 cooling, 3 off
    controller_state=1,  # 0 automatic, 1 override
    learn_button=1,
    energy_holdoff=0,
    occupancy=0,  # 0 occupied, 1 unoccupied, 2 standby
)
command = A5_38_08(5, control_variable=control)
```

The decoded command exposes the same values through
`decoded.control_variable`.

## Command 0x06: fan stage

Fan stages `0` through `3` are explicit stages. `255` selects automatic
control:

```python
stage = A5_38_08(6, fan_stage=2, learn_button=1)
automatic = A5_38_08(6, fan_stage=255, learn_button=1)
```

## Command 0x07: blind/shutter control

The meaning of the two parameter bytes depends on `function`:

- `0`: status request; `1`: stop; `2`: open; `3`: close;
- `4`: drive to position, optionally with angle;
- `5`: open for a time; `6`: close for a time;
- `7`: set runtime; `8`: set angle configuration;
- `9`: set minimum/maximum position;
- `10`: set slat angles for closed/open; `11`: set position logic.

```python
from eltakobus.eep import A5_38_08, CentralCommandBlind

command = A5_38_08(7, blind=CentralCommandBlind(
    parameter_1=25, parameter_2=75, function=4,
    learn_button=1, send_status=1, position_angle=1, service_mode=0,
))
```

`service_mode=1` restricts local operation to the sender that enabled the
mode. Use it only for deliberate maintenance workflows.

## Decoding

The same class decodes compatible incoming commands:

```python
decoded = A5_38_08.decode_message(incoming_message)
if decoded.command == 1:
    print(decoded.switching.switching_command)
elif decoded.command == 5:
    print(decoded.control_variable.control_variable)
```

`WrongOrgError` means the telegram is not a 4BS message. Unsupported command
identifiers raise the library's `NotImplementedError`. All commands produce
the existing `Regular4BSMessage` type, so serial and ESP2 users need no API
migration.

The implementation follows the [official EEP 2.6.8 specification](https://www.enocean-alliance.org/wp-content/uploads/2019/10/EEP268_R3_Feb022018_public.pdf)
and the Eltako [telegram documentation](https://www.eltako.com/fileadmin/downloads/en/_main_catalogue/Gesamt-Katalog_ChT_gb_highRes.pdf).
