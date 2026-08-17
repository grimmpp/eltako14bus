Eltako14Bus Python library
==========================

This repository contains a library and some tools for interacting with the Eltako Series 14 bus system,
which is an extension to the EnOcean Serial Protocol ESP2.

This is part of the reverse engineering approach that allows using Eltako
Series 14 devices without a FAM.

It can work both on a direct RS485 serial connection to the bus,
with or without a FAM14 present on the bus,
through a FAM14's serial connection,
or through a bespoke CoAP interface to the ESP2 protocol.

Tools
-----

The eltakotool program shipped with it can
do various raw interactions with the bus
(replacing some FAM14 functionality, locking and unlocking the bus, sending arbitrary messages)
as well as reading and writing the bus participants' memory
(including verification and annotation of the memory contents).

Developer documentation
-----------------------

The [documentation index](docs/INDEX.md) is the central entry point and groups
the guides by user, application, protocol, testing and release tasks.

The [developer guide](docs/DEVELOPER_GUIDE.md) covers installation, serial and
CoAP transports, asynchronous bus access, discovery, device and EEP APIs,
locking, caching, the command-line tool, offline testing, and extension points.
The [gateway overview](docs/GATEWAYS.md) compares supported gateway families,
protocols, transports, baud rates and usage examples.
The [ESP2 tutorial](docs/TUTORIAL_ESP2.md) and [ESP3 tutorial](docs/TUTORIAL_ESP3.md)
show complete protocol-level examples, including LAN discovery and offline
ESP3 decoding.
The [user guide](docs/USER_GUIDE.md) provides a short operational quick start.
The [release guide](docs/RELEASING.md) documents version selection, local
verification, tagging, GitHub Releases, and PyPI publication.

The independent [device catalog](docs/DEVICE_CATALOG.md) documents device-to-EEP
metadata and lookup helpers. [Teach-in support](docs/TEACH_IN.md) describes the
Eltako-specific sender telegrams, and [compatibility tests](docs/HOME_ASSISTANT_COMPATIBILITY.md)
protect the public API used by external applications without adding a dependency
on Home Assistant.

The complete [EEP reference](docs/EEP_REFERENCE.md) lists all implemented
profiles, organizations, fields, units, and value ranges.
The [D2 v2 migration guide](docs/D2_EEP_MIGRATION.md) explains the correction
of the formerly mislabeled D2-00-01 window-sensor decoder.

The [A5-38-08 command guide](docs/A5_38_08_COMMANDS.md) describes all
supported central switching, dimming, HVAC, fan and blind/shutter commands.

The [library roadmap](docs/ROADMAP.md) records planned protocol, EEP,
diagnostic and testing improvements and clarifies which integration-specific
features intentionally do not belong in this repository.
The [roadmap status](docs/ROADMAP_STATUS.md) records completed milestones,
validation results, the active iteration and the procedure for continuing work.

The [ESP3 framing guide](docs/ESP3_FRAMING.md), [VLD field guide](docs/VLD_FIELDS.md)
and [reference comparison](docs/REFERENCE_COMPARISON.md) document the new
protocol-layer architecture.
The [ESP2 framing guide](docs/ESP2_FRAMING.md) documents the shared parser used
by the TCP and RS485 transports.
The [ESP2 message parser guide](docs/MESSAGE_PARSER.md) documents deterministic
message classification without probing decoder classes through exceptions.
The [ESP3 dispatcher guide](docs/ESP3_DISPATCHER.md) documents typed native
ESP3 packets, serialized command handling, and diagnostics. The opt-in
[EEP schema guide](docs/EEP_SCHEMA.md) documents compatibility-safe D2 schema
migration.
The [UTE session guide](docs/UTE_SESSION.md) documents explicit, fail-closed
teach-in decisions and the separate opt-in learned-device registry.

Quick start
-----------

Install the serial transport and start the included tool with:

```sh
python3 -m pip install -e '.[serial,eltakotool]'
python eltakotool.py --eltakobus /dev/ttyUSB0 enumerate
```

The library is asynchronous. A minimal application creates an
`RS485SerialInterfaceV2`, starts it, awaits `bus.exchange(...)`, and calls
`bus.stop()` during shutdown. See the developer guide for a complete example
and the required baud-rate settings for common gateways.

Protocol description
--------------------

(This is a short version.
The long is partially available in the EnOcean and Eltako documentations,
and the rest is in the reverse engineered code).

The EnOcean serial protocol is a point-to-point serial protocol between a computer and a radio transceiver;
it contains synchronization bytes, some structured data bytes, and checksumming.
The most common message formats are RPS and 4BS,
which have equivalent messages (with short and long (4 byte) data, respectively) on the radio side.
These messages contain some addressing information both when receiving (indicating which device sent it)
and when sending through the transceiver (in which case the addresses need to match the address range of the transceiver, giving about 128 possible sending addresses).

The Eltako protocol is loosely built on the ESP2 protocol,
but is used on an RS485 bus (with up to 127 participants),
and uses several message types that are not defined in ESP2.

Part of the Eltako bus protocol is enumeration:
Devices on the bus can be put into an addressing mode,
and the bus master (a FAM14 or the library user) can assign one of the 127 available address to the device.

Commands are also known to visually identify devices on the bus,
and to read and write their configuration (eg. in a relay, setting which buttons it should react to).

License
-------

Originally developed by Christian Amsüss <c.amsuess@energyharvesting.at> and
Energy Harvesting Solutions (2016–2020). Further developed and maintained by
Philipp Grimm and contributors.

The library is published under the terms of the GNU Lesser General Public
License version 3 or later. See [`LICENSE`](LICENSE). The accompanying GPLv3
text required by the LGPL is preserved in [`LICENSE-GPL-3.0`](LICENSE-GPL-3.0).
