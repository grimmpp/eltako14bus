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

This was developed by Christian Amsüss <c.amsuess@energyharvesting.at> and Energy Harvesting Solutions 2016-2020.

It is published under the terms of GNU LGPL version 3 or later.
