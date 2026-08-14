# Hardware validation report: FAM14 via AQ028YCS

Test date: 2026-08-14 12:01 Europe/Berlin
Serial device: `/dev/tty.usbserial-AQ028YCS`
Adapter: FTDI FT232R USB UART
Baud rate: `57600`
Transport: `RS485SerialInterfaceV2`
Gateway: FAM14 detected automatically

## Connection and bus control

The serial interface connected successfully. The FAM14 acknowledged both bus
locking and bus unlocking:

```text
LOCK: Bus was successfully locked as acknowledged by a FAM
UNLOCK: Bus was successfully unlocked as acknowledged by a FAM
```

Echo detection was disabled for this test. No configuration-memory write was
performed.

## Automatic discovery and complete memory read

Eight devices were discovered. Every advertised memory row was read
successfully; there were no failed rows. The `memory_max_row` value is
inclusive, so a value of `127` means 128 rows (`0..127`).

| Address | Type | Model | Address span | Rows read |
|---:|---|---|---:|---:|
| 1 | FSR14_4x | `04 01 72 00` | 4 | 128 |
| 5 | FUD14 | `04 04 42 00` | 1 | 128 |
| 6 | FSB14 | `04 06 57 00` | 2 | 136 |
| 8 | FAE14SSR | `04 16 51 00` | 2 | 128 |
| 10 | FMZ14 | `04 0E 22 00` | 1 | 128 |
| 11 | FAE14SSR | `04 16 51 00` | 2 | 128 |
| 13 | FGW14_USB | `04 FE 1A 00` | 1 | 128 |
| 14 | FUD14_800W | `04 05 38 00` | 1 | 128 |

Total: **1,032 memory rows read successfully**.

The complete raw memory dump is retained in
[`tests/resources/hardware_test_AQ028YCS_report.json`](../tests/resources/hardware_test_AQ028YCS_report.json).
It contains installation-specific configuration and addresses and should be
handled as a private backup.

## Actuator status and switching test

The first discovered relay (`FSR14_4x`, address 1) was inspected first. Its
channel 0 did not have a direct command entry supported by the current helper,
so no relay command was sent.

The `FUD14` at address 5 had a valid direct command source (`00-00-B0-05`).
Its dimmer status was queried using `EltakoPollForced` and interpreted as:

```text
initial dim: 89
ramping speed: 0
```

The test then performed the following reversible sequence on channel 0:

1. Request dim value `0`.
2. Poll the actuator.
3. Observe dim value `0`.
4. Request the original dim value `89`.
5. Poll the actuator again.
6. Observe dim value `89`.

Both state changes were confirmed by status telegrams on the first poll after
each command. The original state was restored successfully. No memory or
configuration write was used.

The detailed switching result is retained in
[`tests/resources/hardware_test_AQ028YCS_switch_report.json`](../tests/resources/hardware_test_AQ028YCS_switch_report.json).

## Passive receive capture

On 2026-08-14, a 15-second passive run against the detected
`/dev/cu.usbserial-AQ028YCS` port completed successfully. It used 57,600 baud,
disabled echo detection, performed no writes, and received 275 valid
`EltakoPoll` frames. The connection status sequence was:

```text
False -> False -> True -> False
```

The first `False` is emitted when the status handler is registered, the second
is emitted when the worker starts, `True` confirms the connection, and the
final `False` is emitted during clean shutdown. The capture retains 100 raw
ESP2 samples for parser regression tests in
[`tests/resources/hardware_test_AQ028YCS_passive_report.json`](../tests/resources/hardware_test_AQ028YCS_passive_report.json).
`tests/replay_bus_test.py` parses these samples again without opening a serial
port.

## Message-delay benchmark sample

The new `eltakotool.py benchmark` command was also run against FUD14 address 5
with 60 forced polls per candidate and a 0.5-second response timeout. All 240
requests received valid ESP2 responses:

| Delay | Success rate | Throughput |
|---:|---:|---:|
| 0.000 s | 100% | 46.77 messages/s |
| 0.001 s | 100% | 52.31 messages/s |
| 0.005 s | 100% | 41.31 messages/s |
| 0.010 s | 100% | 45.04 messages/s |

The command therefore recommended `0.001 s`. During the high-rate run the
serial parser logged several resynchronization attempts caused by unrelated or
fragmented bus bytes, but no request timed out. This makes the result useful
for tuning, not a guarantee that zero delay is safe. The observation remains
installation- and load-specific; repeat the benchmark when tuning another
gateway or a bus with different traffic.

## Reproduction

The passive hardware soak test remains opt-in:

```sh
ELTAKO_SERIAL_HARDWARE_TEST=1 \
ELTAKO_SERIAL_PORTS=/dev/cu.usbserial-AQ028YCS \
ELTAKO_SERIAL_TEST_SECONDS=30 \
python -m unittest tests.serial_hardware_test -v
```

The complete memory read and switching sequence was run as an explicit
maintenance test against the configured FAM14 setup. It should not be added
to the default CI suite because it requires the physical installation and can
change actuator state temporarily.
