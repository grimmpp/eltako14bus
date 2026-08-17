# Gateway overview

This document distinguishes the gateway hardware name from the transport used
to reach it. A gateway can expose ESP2, ESP3, CoAP or a vendor-specific network
interface; the transport class must match the wire protocol, not just the
product name.

## Supported gateway families

| Catalog/type | Typical role | Wire protocol | Library transport | Baud rate |
|---|---|---|---|---:|
| `fam14` / FAM14 | Eltako Series 14 bus gateway | Eltako ESP2-like bus telegrams | `RS485SerialInterfaceV2` | 57600 |
| `fgw14usb` / FGW14-USB | USB connection to the Series 14 bus | Eltako ESP2-like bus telegrams | `RS485SerialInterfaceV2` | 57600 |
| `fam-usb` / FAM-USB | EnOcean/FAM USB transceiver | ESP2 | `RS485SerialInterfaceV2` | 9600 |
| `enocean-usb300` / USB300 | EnOcean USB transceiver | ESP3 | native ESP3 parser/models; transport supplied by the application | device-specific |
| `esp3-gateway` / MGW USB | ESP3 radio gateway | ESP3 | native ESP3 parser/models; transport supplied by the application | device-specific |
| `lan-gw-esp2` | Network gateway exposing ESP2 | ESP2 over TCP | `ESP2TCPSerialInterface` | not applicable |
| `lan` / MGW LAN | Network gateway exposing ESP3 or vendor protocol | commonly ESP3/network protocol | application-specific transport; native ESP3 models can be used after framing | not applicable |
| `mgw-lan`, `eul_lan` | Catalog classifications for LAN gateways | product-dependent | no dedicated adapter in this package | not applicable |

`GatewayDeviceType` also contains the stable names used by the catalog and
diagnostic helpers. The catalog includes a few hardware aliases such as
`FTD14` and `FGW14`; these identify hardware but do not currently select a
separate transport implementation.

## Choosing the transport

### Local serial ESP2 gateways

Use the recommended threaded interface for FAM14, FGW14-USB and FAM-USB:

```python
from eltakobus.const import baud_rate_for
from eltakobus.serial import RS485SerialInterfaceV2

gateway_type = "fam14"
bus = RS485SerialInterfaceV2(
    "/dev/ttyUSB0",
    baud_rate=baud_rate_for(gateway_type),
    auto_reconnect=True,
)
bus.start()

# The normal BusInterface methods can now be used, for example:
# response = await bus.exchange(request, ResponseType)
```

The older `RS485SerialInterface` remains available for applications that use
the asyncio protocol API. New code should normally use
`RS485SerialInterfaceV2`, which has the threaded receiver, shared ESP2 frame
parser and reconnect handling.

Use `scan_serial_ports()` for passive port enumeration. It only inspects
descriptors and filesystem links; it does not open or probe a port. Use
`async_read_identity()` only with an already-owned bus and a supported gateway
type.

### ESP2 over TCP

For a LAN adapter that forwards the Eltako ESP2 stream, use
`ESP2TCPSerialInterface`:

```python
from eltakobus.esp2_gateway import ESP2TCPSerialInterface

bus = ESP2TCPSerialInterface(
    "192.168.1.50",
    port=5000,
    auto_reconnect=True,
)
bus.start()

try:
    # await bus.exchange(request, ResponseType)
    pass
finally:
    bus.stop()
    bus.join(timeout=2)
```

This adapter speaks the same 14-byte ESP2 message format as the serial
interface. `ESP2TCP2SerialCommunicator` is retained as a compatibility alias.
The TCP adapter does not need `zeroconf`; host names, IP addresses and port
selection are supplied by the application.

### ESP3 gateways

ESP3 support is protocol-native but intentionally transport-neutral:

```python
from eltakobus.esp3_frame import ESP3FrameParser
from eltakobus.esp3_packet import decode_esp3_packet

parser = ESP3FrameParser()
for frame in parser.feed(raw_bytes_from_your_transport):
    packet = decode_esp3_packet(frame)
    print(packet)
```

`RadioTelegram`, `ESP3Response`, `ESP3Event`, `ESP3Command` and
`ESP3Dispatcher` preserve ESP3 information without requiring the historic
`enocean` package. This package currently does not open a dedicated ESP3
serial/TCP device itself; an application or gateway adapter supplies raw ESP3
bytes and can then use the native parser and dispatcher.

### CoAP gateways

For gateways that expose the library's existing CoAP endpoint, use the optional
CoAP transport:

```python
import aiocoap
from eltakobus.coap import CoAPInterface

context = await aiocoap.Context.create_client_context()
bus = CoAPInterface(context, "coap://gateway.example/raw")
```

Install the optional dependency with `pip install 'eltako14bus[coap]'`.
The CoAP interface is separate from ESP2-over-TCP and does not imply that a
gateway also supports raw ESP3 framing.

## Identity and capability checks

```python
from eltakobus.const import baud_rate_for
from eltakobus.gateway_identity import identity_capabilities

caps = identity_capabilities("fam-usb")
print(caps["baud_rate"])
print(caps["can_read_base_id"])
```

Identity helpers describe supported probes; they do not open a second serial
handle. In particular, the current native ESP2 identity request is for
FAM-USB. ESP3 identity requests depend on the application-provided ESP3
transport.

## Discovery scope

Passive LAN-gateway discovery is available through
`eltakobus.lan_discovery.LanGatewayDiscovery`. It observes the reference mDNS
services `_bsc-sc-socket._tcp.local.` and `_tcm515._tcp.local.` and exposes
name, hostname, IPv4 address, port, service type and `GatewayDeviceType`.
It does not connect to a gateway or send telegrams.

```python
from eltakobus.lan_discovery import LanGatewayDiscovery

discovery = LanGatewayDiscovery()
discovery.start()
try:
    endpoint = discovery.find_endpoint(gateway_device_type="lan")
    if endpoint is not None:
        print(endpoint.hostname, endpoint.endpoint, endpoint.gateway_device_type)
finally:
    discovery.stop()
```

The `zeroconf` dependency is lazy and optional:
`pip install 'eltako14bus[discovery]'`. SmartConn and EUL services map to
`GatewayDeviceType.LAN`; Virtual-Network-Gateway-Adapter maps to
`GatewayDeviceType.LAN_ESP2`. The class also supports injected fake factories
and direct `add_service`, `update_service` and `remove_service` calls for
offline tests.

The same passive scan is available from the command line:

```sh
eltakotool.py lan_scan --wait 3 --json
```

## Quick selection guide

| Situation | Use |
|---|---|
| FAM14 or FGW14-USB connected locally | `RS485SerialInterfaceV2`, 57600 baud |
| FAM-USB connected locally | `RS485SerialInterfaceV2`, 9600 baud |
| LAN device forwards 14-byte ESP2 messages | `ESP2TCPSerialInterface` |
| USB/LAN device provides ESP3 frames | `ESP3FrameParser` and native ESP3 models |
| Gateway exposes the supported CoAP endpoint | `CoAPInterface` with the `coap` extra |
| Need to find local serial ports | `scan_serial_ports()`; passive only |
