# Eltako14Bus developer guide

This guide describes how to use and extend `eltako14bus`, a Python library for
Eltako Series 14 RS485 installations. It is written for developers integrating
the library into an application, automation service, diagnostic tool, or test
suite.

The library speaks the Eltako bus protocol, which is related to EnOcean Serial
Protocol 2 (ESP2), but is not a drop-in ESP2 implementation. In particular,
the Eltako bus has its own bus locking, discovery, memory, and polling
messages. The library can communicate through a serial adapter or through the
project's raw CoAP endpoint.

## Scope and safety

Most read operations are safe to run against a live installation. The
following operations change installation state and should be treated as
maintenance operations:

- `write_mem_line()` and the `reprogram` command write device configuration.
- `ensure_programmed()` changes an actuator's programmed sender table.
- `set_state()` sends an actuator command.
- `lock_bus()` temporarily changes how a FAM14 controls the bus.

Always make a memory dump before changing configuration. Do not run two
clients that exchange messages on the same bus concurrently: an exchange
temporarily owns the receive queue and can otherwise consume another client's
response.

## Installation

The package requires Python 3. The optional dependencies correspond to the
available transports and tools:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[serial]'
```

Install CoAP support instead, or in addition, when using `CoAPInterface`:

```sh
python -m pip install -e '.[coap]'
```

The `eltakotool.py` utility additionally needs the `eltakotool` extra:

```sh
python -m pip install -e '.[serial,eltakotool]'
```

The repository's `requirements.txt` is a convenient development dependency
list, but the authoritative transport-specific package definitions are in
`setup.py`.

The core package keeps CoAP and YAML-backed device helpers optional at import
time. This means message parsing, passive port discovery, and identity parsing
can be used in a minimal installation; install the corresponding extras before
using `CoAPInterface` or YAML device helpers.

## Architecture

The public package re-exports the main modules from `eltakobus.__init__`, so
existing applications often use `from eltakobus import ...`. For new code,
explicit imports are preferable because they make dependencies clear.

The layers are:

1. **Transport** — `RS485SerialInterfaceV2` or `CoAPInterface` moves 14-byte
   ESP2-compatible frames.
2. **Bus abstraction** — `BusInterface.exchange()`, `send()`, and `read_mem()`
   provide asynchronous request/response operations.
3. **Message model** — `ESP2Message`, `EltakoMessage`, discovery, memory,
   polling, RPS, and 4BS classes serialize and parse frames.
4. **Device model** — `create_busobject()` and device subclasses turn
   discovery replies into typed devices with memory and actuator helpers.
5. **EEP model** — EEP classes encode and decode application data such as
   switch, temperature, humidity, and actuator telegrams.

All bus I/O is asynchronous. The serial V2 transport itself runs a worker
thread, but its public API is still awaited from the application's event loop.

## Connecting to a serial bus

`RS485SerialInterfaceV2` is the recommended serial backend. Start its worker
thread, wait until it reports a connection, use it from an async function, and
stop it during shutdown:

```python
import asyncio

from eltakobus.error import TimeoutError
from eltakobus.message import EltakoDiscoveryRequest, EltakoDiscoveryReply
from eltakobus.serial import RS485SerialInterfaceV2


async def main() -> None:
    bus = RS485SerialInterfaceV2(
        "/dev/ttyUSB0",
        baud_rate=57600,
        auto_reconnect=True,
        reconnection_timeout=10,
    )
    bus.start()
    try:
        # The worker connects in the background. Waiting here avoids sending
        # the first request before the serial port is ready.
        await asyncio.to_thread(bus.is_serial_connected.wait)

        try:
            reply = await bus.exchange(
                EltakoDiscoveryRequest(address=1), EltakoDiscoveryReply
            )
        except TimeoutError:
            print("No device answered at bus address 1")
        else:
            print(reply)
    finally:
        bus.stop()
        await asyncio.to_thread(bus.join)


asyncio.run(main())
```

Typical adapter settings are 57,600 baud for FAM14/FAM15 and FGW14-USB, and
9,600 baud for FAM-USB. Confirm the setting for the actual gateway before
connecting. The serial backend performs echo detection by default. Set
`disabled_echotest=True` when the adapter does not support the detection
sequence or when a test double provides serial semantics without an echo.

Useful connection options include `callback=callable` for event-driven
receiving, `delay_message` for gateways with a small internal buffer,
`auto_reconnect` for recovery after serial errors, and
`set_status_changed_handler(handler)` for connection status changes. Do not
use callback mode and `exchange()` concurrently.

### Measuring message delay

The command-line tool can measure request/response behavior for several
`delay_message` values. It sends only forced-poll requests to the selected bus
address; it does not write configuration memory or change actuator state:

```sh
python eltakotool.py \
  --eltakobus /dev/cu.usbserial-AQ028YCS \
  benchmark 5 \
  --messages 20 \
  --delays 0,0.001,0.002,0.005,0.01,0.02
```

The output reports successful responses, timeouts, response rate, throughput,
and the highest-throughput tested delay meeting the configured minimum success
rate. The recommendation is valid only for the tested setup.
The same measurement is available in Python as
`eltakotool.benchmark_message_delays(bus, request_factory, ...)`, returning a
list of result dictionaries. Delay requirements depend on the gateway,
adapter, bus traffic, and connected devices.

### Connecting through an ESP2 gateway adapter

The library provides `ESP2TCPSerialInterface` for gateways that expose the
ESP2 stream over TCP, as used by the
[esp2_gateway_adapter project](https://github.com/grimmpp/esp2_gateway_adapter):

```python
import asyncio

from eltakobus.esp2_gateway import ESP2TCPSerialInterface
from eltakobus.message import EltakoDiscoveryRequest, EltakoDiscoveryReply


async def main():
    bus = ESP2TCPSerialInterface("192.168.1.50", 5000, auto_reconnect=True)
    bus.start()
    try:
        await asyncio.to_thread(bus.is_serial_connected.wait)
        print(await bus.exchange(EltakoDiscoveryRequest(1), EltakoDiscoveryReply))
    finally:
        bus.stop()
        await asyncio.to_thread(bus.join)


asyncio.run(main())
```

It handles fragmented/coalesced 14-byte ESP2 frames, unsolicited frames via
`bus.received` or `set_callback()`, clean shutdown, and automatic reconnect.
The `socket_factory` argument lets unit tests provide a socket-like double.
The ESP3/EnOcean dependency is intentionally not imported by the core package;
an ESP3 radio can be used when the external project provides the ESP2 endpoint.

For applications that directly use an ESP3 communicator, install the optional
dependency with `python -m pip install -e '.[esp3]'` and use
`ESP3MessageAdapter`. It adds the ESP3 RADIO_ERP1 Security-Level byte and
isolates conversion errors:

```python
from eltakobus.esp3 import ESP3MessageAdapter

adapter = ESP3MessageAdapter()

# In the ESP3 receive callback. Invalid packets return None and are logged.
converted = adapter.handle_packet(packet, callback, translate=True)
```

Do not let a conversion exception escape from an ESP3 receive worker. Unknown
return codes, `WRONG_PARAM`, short payloads, unsupported RORGs, and callback
failures are logged and ignored so that subsequent radio telegrams can still
be processed.

The older `RS485SerialInterface` remains in the source tree for compatibility.
New integrations should use V2 unless they specifically need the legacy
asyncio protocol lifecycle.

## Gateway discovery and diagnostics

The library also contains the reusable parts of the standalone gateway tools
from the Home Assistant Eltako integration. `scan_serial_ports()` performs a
passive scan and returns `SerialPortInfo` objects with pyserial descriptors,
stable `/dev/serial/by-id` links, and non-authoritative device-type hints. It
never opens or writes a port:

```python
from eltakobus.gateway_scan import scan_serial_ports

for port in scan_serial_ports():
    print(port.device, port.suggested_device_types, port.by_id)
```

Use `eltakobus.gateway_identity` for the protocol-level pieces of an active
probe: `fam_usb_base_id_request()`, `parse_fam_usb_base_id()`, and
`parse_version_response()`. `async_read_identity()` can read a FAM-USB identity
through an already-owned `BusInterface`; it does not open a second serial
handle. An active probe must not run against a port that is
already owned by a running gateway because opening it can interrupt reception.
The passive scan is therefore intentionally separate from identity reading.

For command-line tools and test runners, `eltakobus.diagnostics` provides
small, serializable building blocks. `probe_devices()` records successful
discoveries and timeouts per address, while `read_memory_test()` reads a full
memory image and returns a report instead of aborting a complete diagnostic
run. Both work with a real `BusInterface` and with replay/fake buses.

The Home Assistant-specific websocket commands, entity constants, config-flow
keys, and UI state from `home-assistant-eltako` are deliberately not part of
this library. They depend on Home Assistant and would make the core package
harder to embed.

## Using the CoAP backend

`CoAPInterface` expects an already-created `aiocoap` client context and a URI
for the raw ESP2 resource:

```python
import asyncio
import aiocoap

from eltakobus.coap import CoAPInterface
from eltakobus.message import EltakoDiscoveryRequest, EltakoDiscoveryReply


async def main() -> None:
    context = await aiocoap.Context.create_client_context()
    bus = CoAPInterface(context, "coap://gateway.example/raw")
    reply = await bus.exchange(
        EltakoDiscoveryRequest(1), EltakoDiscoveryReply
    )
    print(reply)
    await context.shutdown()


asyncio.run(main())
```

The CoAP backend also implements `read_mem()` through its `memory` endpoint.
The endpoint layout is specific to the gateway service; adjust the URI to the
service actually deployed in your installation.

## Exchanges, sends, and errors

`BusInterface.exchange(request, responsetype=None)` sends a request and waits
for a response. Passing a response class is recommended because it validates
the expected message shape:

```python
from eltakobus.error import ParseError, TimeoutError
from eltakobus.message import EltakoMemoryRequest, EltakoMemoryResponse, EltakoMessage

try:
    response = await bus.exchange(
        EltakoMemoryRequest(address=1, row=0), EltakoMemoryResponse
    )
except TimeoutError:
    response = None
except ParseError:
    raise
```

Use `send()` only when no response is expected:

```python
await bus.send(EltakoMessage(
    org=0x05, address=0x01,
    payload=b"\x10\x00\x00\x00\x00\x00\x00\x00",
))
```

`ESP2Message.parse()` validates the preamble, length, and checksum. Use the
specific class's `parse()` method when the message type is known. `prettify()`
is useful for logs and exploratory tools, but application logic should not
depend on whichever subtype happens to be first in its parser list.

## Discovery and typed devices

Discovery asks a bus address for its model, address span, and memory size.
`create_busobject()` performs this request and selects the best-known device
class; unknown devices become a generic `BusObject`:

```python
from eltakobus.device import create_busobject

device = await create_busobject(bus, 1)
if device is None:
    print("Address did not answer")
else:
    print(device, device.memory_size, device.version)
    memory = await device.read_mem()
```

For a complete scan, iterate addresses and handle timeouts. A device can
occupy more than one address, so skip the remainder of `device.size` after a
successful discovery. The command-line tool's `enumerate_bus()` implements
this policy and is a useful reference.

Common device operations are:

```python
memory = await device.read_mem()
line = await device.read_mem_line(0)
await device.write_mem_line(0, line)       # writes; validate first

if hasattr(device, "get_all_sensors"):
    sensors = await device.get_all_sensors()
```

Specialized classes expose additional methods. For example, dimmer-style
devices provide `set_state(channel, dim, total_ramp_time=0)`, while switching
devices provide `set_state(channel, state)`. Check the concrete class before
calling a device-specific method; unknown hardware is intentionally represented
by the safer generic `BusObject`.

## Bus locking

When a FAM14 is present, maintenance operations should run while the bus is
locked. The lock helper waits for the FAM's acknowledgement and detects a FAM
that is continuously scanning in mode 1:

```python
from eltakobus import locking

locked = False
try:
    result = await locking.lock_bus(bus)
    locked = result == locking.LOCKED
    # enumerate, read, or write here
finally:
    if locked:
        await locking.unlock_bus(bus)
```

If no FAM is present, the helper returns `PROBABLY_LOCKED` after retries. This
means the library assumes that it can proceed, not that an acknowledgement was
received. `BadFAMMode1` indicates that another bus-management mode must be
resolved before continuing. The `@buslocked` decorator automates the
lock/finally-unlock pattern for a coroutine whose first argument is the bus.

## Caching and memory prefetch

`RAMBusCache` and `PickledBusCache` cache discovery and memory responses after
the bus has been successfully locked. `PickledBusCache` persists the cache to
a `pathlib.Path`. `ReadaheadPickledBusCache` additionally reads complete device
memory when a single memory row is requested:

```python
from pathlib import Path
from eltakobus.bus import ReadaheadPickledBusCache

bus = ReadaheadPickledBusCache(bus, Path("eltakobus-cache.pkl"))
```

Caching is useful for repeated inspection, but it can make verification
misleading if a cache is reused after a device changes. Do not enable it for a
fresh verification unless the cache is known to be current. Writes invalidate
the relevant cached memory entries.

## EEP encoding and decoding

EEP classes model the application payload of radio-style RPS and 4BS
telegrams. Look up a profile by its standard name, decode an incoming message,
or create an outgoing message for an address:

```python
from eltakobus.eep import A5_04_02, EEP

profile = EEP.find("A5-04-02")
decoded = profile.decode_message(incoming_message)
print(decoded.current_temperature, decoded.humidity)

outgoing = A5_04_02(temperature=200, humidity=500, learn_button=1)
message = outgoing.encode_message(bytes.fromhex("FF DD CC BB"))
await bus.send(message)
```

Constructor arguments and value ranges differ by EEP. Inspect the concrete
class and its properties before constructing a message. `WrongOrgError`
means that the message's ORG does not match the profile; `ParseError` means
that the frame itself is malformed or has the wrong shape.

Every registered profile exposes structured metadata through `metadata` and
`get_metadata()`:

```python
from eltakobus.eep import EEP

profile = EEP.find("A5-10-06")
info = profile.get_metadata()
print(info.eep, info.name, info.description, info.org)
for field in info.fields:
    print(field.name, field.unit, field.value_range, field.values)

# Useful when exposing EEP information through a REST or JSON API.
payload = info.as_dict()
```

`EEPFieldMetadata.value_range` describes the physical/logical value exposed by
the Python object, while `values` describes enumerations and bit flags. The
metadata is descriptive and does not replace validation performed by the EEP
encoder.

`AddressExpression` represents a four-byte address with an optional
discriminator such as `"00-21-63-43 left"`:

```python
from eltakobus.util import AddressExpression

source = AddressExpression.parse("FF-DD-CC-BB left")
print(str(source))
plain = source.plain_address()  # raises ValueError when a discriminator exists
```

## Command-line tool

The repository includes `eltakotool.py`. It is currently a script rather than
an installed console entry point, so run it from the checkout:

```sh
python eltakotool.py --eltakobus /dev/ttyUSB0 enumerate
python eltakotool.py --eltakobus /dev/ttyUSB0 --baud_rate 57600 listen
python eltakotool.py --eltakobus /dev/ttyUSB0 dump bus.yaml
python eltakotool.py --eltakobus /dev/ttyUSB0 verify bus.yaml
python eltakotool.py --eltakobus /dev/ttyUSB0 show_off
```

Full usage, including every subcommand's options, is always available from the
tool itself:

```sh
python eltakotool.py --help
python eltakotool.py <command> --help
```

### Global options

| Option | Description |
| --- | --- |
| `--rawuri URI` | Connect through a raw ESP2 CoAP endpoint. Conflicts with `--eltakobus`. |
| `--eltakobus DEVICE` | Connect through a serial device (e.g. `/dev/ttyUSB0`). Conflicts with `--rawuri`. |
| `--baud_rate RATE` | Baud rate for the transmitter or gateway (default `57600`). FAM15 and FGW14-USB use `57600`; FAM-USB uses `9600`. |
| `--serial_lib_version {1,2}` | Serial backend: `2` (default) selects `RS485SerialInterfaceV2`, a threaded implementation with auto-reconnect; `1` selects the legacy asyncio-protocol-based `RS485SerialInterface`. |
| `--cache` | Cache exchange responses locally (see [Caching and memory prefetch](#caching-and-memory-prefetch)). |
| `--cachefile PATH` | Explicit cache file location; defaults to an XDG cache path derived from the transport. |
| `--preread` | Enumerate the bus and read every device's memory before running the command. Only useful together with `--cache`. |
| `--log_level LEVEL` | Standard library log level name, e.g. `debug`, `info`, `warning` (default `info`). |
| `--version` | Print the installed package version and exit. |

Exactly one of `--rawuri` or `--eltakobus` is required; the tool does not yet
support autodiscovery.

### Commands

| Command | Purpose | Changes bus/device state? |
| --- | --- | --- |
| `enumerate` | Scan addresses 1-254, print discovered devices, then offer to assign an address to a device in LRN mode. | Yes — address assignment |
| `fakefam DEVICE` | Act as a FAM14 towards a client connected on `DEVICE` (serial port, unix socket path, or `host:port`), by relaying its ESP2 requests onto the real bus. | No (relays only) |
| `send_raw B0 B1 ... B10` | Send a single raw ESP2 telegram given as eleven hexadecimal bytes (`h_seq/len org data... id status`) and print the response. | Depends on the telegram sent |
| `eval EXPR` | Evaluate `EXPR` as a Python expression that builds a message object (all `eltakobus` message classes are in scope), send it, and print the response. Runs the expression through `eval()` — a local debugging aid, not for untrusted input. | Depends on the expression |
| `lock_bus` | Lock the bus so a FAM stops driving it. | Yes |
| `unlock_bus` | Release the bus back to normal FAM operation. | Yes |
| `show_off [SEARCHTERM]` | Discover devices (optionally filtered by address or type name) and cycle through a demo of what each one can do. | Yes — triggers actuator demos |
| `dump [FILENAME]` | Read every discovered device's memory and store it in a YAML file (default `bus.yaml`). | No |
| `verify [FILENAME]` | Compare live device memory against a previously stored dump and report differing rows; exits with status 1 if any differ. | No |
| `reprogram [FILENAME]` | Write memory rows from a dump file to the matching live devices wherever they differ. | **Yes — writes device configuration** |
| `listen [--ensure-unlocked]` | Print bus traffic as it happens without sending anything. `--ensure-unlocked` locks and releases the bus first to force a FAM to re-enumerate. | Only with `--ensure-unlocked` |
| `automode` | Detect what is currently driving the bus (FAM present, scanning, polling), report it, then fall through to `listen`. | No |

Raw telegrams accept eleven hexadecimal bytes in the tool's ESP2 body order:

```sh
python eltakotool.py --eltakobus /dev/ttyUSB0 send_raw \
  0b 05 10 00 00 00 00 00 ff dd cc
```

`fakefam` is useful for running the tool's own memory or verification commands
against production software (e.g. a PCT14/FAM14 client) while still allowing
`eltakotool.py` itself to talk to the real bus:

```sh
python eltakotool.py --eltakobus /dev/ttyUSB0 fakefam /tmp/fakefam.sock
```

Use `--rawuri` instead of `--eltakobus` for a raw CoAP endpoint. `enumerate`,
`lock_bus`, `unlock_bus`, `show_off`, `dump`, `verify`, and especially
`reprogram` are maintenance commands. Review the output and keep a backup
before using them.

## Testing without hardware

The `tests/` directory contains offline unit tests covering EEP construction
(`generic_eep_test.py`), both serial transports (`serial_test.py`), a replay of
a recorded hardware session (`replay_bus_test.py`), and `eltakotool.py`'s
argument parsing and `fakefam` fallback logic (`eltakotool_test.py`). The
package import currently loads the serial and CoAP backends, and
`eltakotool.py` additionally imports `xdg.BaseDirectory`, so install both
extras before running the suite. Then use the standard library test runner;
`pytest` itself is not required:

```sh
python -m pip install -e '.[serial,coap,eltakotool]'
python -m unittest discover -s tests -p '*_test.py' -v
```

If pytest is installed, the same tests can be run with:

```sh
python -m pytest -q
```

`generic_eep_test.py` enumerates all registered EEP subclasses and verifies
that each supported profile can be instantiated from its constructor
signature. `eltakotool_test.py` calls `eltakotool.build_arg_parser()` directly
to check option defaults and types (for example, that `--serial_lib_version`
and `--baud_rate` parse to `int`, not `str`) without touching a real bus, and
exercises `fakefam()`'s serial-vs-socket fallback with patched
`serial_asyncio`/`asyncio` calls. A small offline smoke test for message
serialization is also useful when developing a transport:

```python
from eltakobus.message import EltakoDiscoveryRequest, ESP2Message

request = EltakoDiscoveryRequest(1)
wire = request.serialize()
assert len(wire) == 14
assert ESP2Message.parse(wire).serialize() == wire
```

For transport tests, implement a fake `BusInterface.base_exchange()` that
returns serialized response bytes. This lets discovery, memory, locking, and
device code be tested without opening a serial port. Keep fake responses as
real 14-byte messages so checksum and parser behavior are exercised.

An opt-in hardware soak test is available in
`tests/serial_hardware_test.py`. It opens two configured FTDI ports in
parallel, receives existing traffic, and sends no frames. Because it accesses
real devices, it is skipped by default:

```sh
ELTAKO_SERIAL_HARDWARE_TEST=1 \
ELTAKO_SERIAL_TEST_SECONDS=30 \
python -m unittest tests.serial_hardware_test -v
```

Review the `PORTS` tuple and `baud_rate` in that test before using it with a
different installation, or set `ELTAKO_SERIAL_PORTS` to a comma-separated
list of ports. Do not turn this test into a transmitting load test
unless the adapters are connected to an isolated test bus or a loopback
fixture.

Unavailable configured ports are ignored. If none of the configured ports can
be opened, the hardware tests are reported as skipped rather than failed, so
they remain safe to run on developer machines and in CI without adapters.

The recorded validation result for the AQ028YCS/FAM14 setup is documented in
[`docs/HARDWARE_TEST_AQ028YCS.md`](HARDWARE_TEST_AQ028YCS.md).

The serial unit tests also simulate an adapter disappearing during active
receiving. `test_auto_reconnects_after_serial_interface_disappears` verifies
that the failed port is closed, the connection status is cleared, a new port
is opened after the reconnection delay, and bus traffic is received again.
The test uses no hardware and is protected by timeouts so a reconnect bug
cannot leave the test process waiting indefinitely.

The recorded session is also used by `tests/replay_bus_test.py` as an offline
bus simulation. It replays discovery, all memory rows, FUD14 status polling,
and the generated dimming command without opening a serial port:

```sh
python -m unittest tests.replay_bus_test -v
```

Keep the JSON recording synchronized with the replay assertions when the
hardware fixture is regenerated. The recording contains installation-specific
configuration and addresses and should not be replaced with data from a
different installation without reviewing the test expectations.

When adding a new EEP, add a concrete class whose name follows the
`XX_XX_XX` convention. `EEP.__init_subclass__` registers it automatically;
extend the generic test only when the profile needs an explicit exception or
special setup.

## Extending the library

### New message type

Add a class in `message.py` with a constructor for semantic fields, a
`serialize()`-compatible `body`, and a strict `parse()` method that raises
`ParseError` for unrelated messages. Add it to `prettify()` only if it is
useful for diagnostics. Add round-trip tests for valid frames and rejection
tests for wrong ORG, direction, length, and checksum.

### New device type

Subclass `BusObject` or the closest capability mixin, define `discovery_names`
and `size`, and implement only operations supported by the hardware. Register
the class in the `known_objects` list in `device.py`; the list is sorted so
more specific matches should be preferred. Test discovery with a synthetic
`EltakoDiscoveryReply` and use a fake bus for memory and command methods.

### New transport

Subclass `BusInterface` and implement `base_exchange()`. It must accept an
`ESP2Message` and return the serialized response bytes expected by the default
`exchange()` implementation. If the transport needs custom timeout or queue
behavior, override `exchange()` while preserving `TimeoutError` semantics.

## Troubleshooting

**No response / `TimeoutError`** — verify the serial device, baud rate, bus
power, gateway mode, and that another process is not consuming the bus. A FAM
may also be busy scanning; use the locking helper and handle `BadFAMMode1`.

**Checksum or `ParseError`** — inspect raw bytes with `prettify()` and enable
logging (`logging.basicConfig(level=logging.DEBUG)`). For serial adapters,
check echo handling and try `disabled_echotest=True` only when echo detection
is known to be incompatible.

**Unexpected device class** — print the discovery reply's model and reported
size. Unknown or newly released hardware falls back to `BusObject` until its
model identifier and address span are added to `known_objects`.

**Stale values** — remove or replace the pickled cache, or disable caching for
the operation. Cache entries are deliberately retained across runs.

**Concurrent access errors** — serialize all calls to `exchange()` for one
transport. Callback mode is an alternative for event-driven consumers, but it
cannot safely be mixed with request/response exchange.

## Compatibility notes

The package is released under LGPLv3 or later. The public API is evolving and
some names reflect reverse-engineered protocol behavior. Prefer the documented
high-level classes and keep raw message construction isolated in integration
code. When reporting a bug, include Python version, package version, transport
type, gateway model, baud rate, sanitized raw frames, and the smallest
reproducible example.
