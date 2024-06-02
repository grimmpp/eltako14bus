#!/usr/bin/env python3

import argparse
import asyncio
import functools
import os
import time
import sys
from pathlib import Path
import logging

from typing import Optional

import xdg.BaseDirectory

from eltakobus import *
from eltakobus.eep import *
from eltakobus.locking import buslocked

async def enumerate_bus(bus, *, limit_ids=None):
    """Search the bus for devices, yield bus objects for every match"""

    if limit_ids is None:
        limit_ids = range(1, 256)

    skip_until = 0

    for i in limit_ids:
        try:
            if i > skip_until:
                bus_object = await create_busobject(bus, i)
                if bus_object != None:
                    skip_until = i + bus_object.size -1
                    yield bus_object
        except TimeoutError:
            continue

@buslocked
async def enumerate_cmd(bus):
    print("Scanning the bus for devices with addresses...")
    usage_map = [False] * 256
    async for dev in enumerate_bus(bus):
        print("Discovered: %s"%dev)
        usage_map[dev.address:dev.address+dev.size] = [True] * dev.size

    print("Bus scan completed.")

    reported = False
    while True:
        try:
            response = await bus.exchange(EltakoDiscoveryRequest(address=0), EltakoDiscoveryReply)
        except TimeoutError:
            if reported is False:
                print("You may now put a device into LRN mode to automatically assign an address.")
                reported = True
        else:
            print("A device is available in LRN mode (model %s, size %d)."%(b2a(response.model), response.reported_size))
            for i in range(1, 254 - response.reported_size):
                if not any(usage_map[i:i+response.reported_size]):
                    break
            else:
                raise Exception("No suitable free space in usage map")

            usage_map[i:i+response.reported_size] = [True] * response.reported_size
            response = await bus.exchange(EltakoMessage(org=0xf8, address=i), EltakoDiscoveryReply)
            if response.reported_address == 0:
                print("Assigning may not have worked, marking area as dirty and trying again...")
                continue
            assert response.reported_address == i, "Assigning bus number %d resulted in response %r"%(i, response)
            print("The device was assigned bus address %d. You may now put a further device into LRN mode."%i)


@buslocked
async def preread(bus):
    """Given a partial'd exchange function, read once through all addresses and all their memory content"""

    for i in range(256):
        try:
            r = await bus.exchange(EltakoDiscoveryRequest(address=i), EltakoDiscoveryReply)
        except TimeoutError:
            continue

        print("Scanning memory of %d"%i)
        await bus.read_mem(i)

async def run_fakefam(bus, reader, writer, conn_made: Optional[asyncio.Future]=None, conn_end: Optional[asyncio.Future]=None):
    if conn_made:
        conn_made.set_result(None)
    buffered = b""

    while True:
        try:
            buffered += await reader.readexactly(14 - len(buffered))
        except asyncio.streams.IncompleteReadError:
            break
        while len(buffered) >= 14:
            try:
                parsed = ESP2Message.parse(buffered[:14])
            except ParseError:
                buffered = buffered[1:]
            else:
                buffered = buffered[14:]

                start = time.time()
                response = await bus.exchange(parsed, ESP2Message)
                end = time.time()
                print(prettify(parsed), "(%.3fs)"%(end - start), prettify(response))
                writer.write(response.serialize())

    if conn_end:
        conn_end.set_result(None)

async def fakefam(bus, serverdevice):
    # serverdevice will be tested to be a character device, and otherwise
    # opened as a unix or tcp socket depending on whether it contains slashes
    # or colons.
    loop = asyncio.get_event_loop()

    try:
        # reader, writer = await serial_asyncio.open_serial_connection(serverdevice, baudrate=57600, loop=loop)
        # the above should work as well -- this is a workaround for not-sure-what
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await serial_asyncio.create_serial_connection(loop, lambda: protocol, serverdevice, baudrate=57600)
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        await run_fakefam(bus, reader, writer)
    except serial.serialutil.SerialException:
        pass
    else:
        def read():
            return os.read(s.fileno(), 1024)
        write = s.write

        q = asyncio.Queue(loop=loop)
        loop.add_reader(s.fileno(), lambda: q.put_nowait(read()))
        return

    conn_end = asyncio.Future()
    if '/' in serverdevice or not ':' in serverdevice:
        conn_made = asyncio.Future()
        await asyncio.start_unix_server(functools.partial(run_fakefam, bus, conn_made=conn_made, conn_end=conn_end), serverdevice, loop=loop)
        await conn_made
        os.unlink(serverdevice)
    else:
        # note that this could run several connections at the same time, which is both great and terrifying
        host, port = serverdevice.split(':', 1)
        await asyncio.start_server(functools.partial(run_fakefam, bus, conn_end=conn_end), host, int(port), loop=loop)
    await conn_end

async def send_raw(bus, data):
    print(prettify(await bus.exchange(ESP2Message(bytes(data)), ESP2Message)))

async def lock_bus(bus):
    print(await(locking.lock_bus(bus)))

async def unlock_bus(bus):
    print(await(locking.unlock_bus(bus)))

@buslocked
async def show_off(bus, search_term=""):
    devices = []

    print("Scanning the bus for devices with addresses...")

    try:
        search_term_int = int(search_term)
    except ValueError:
        scan = range(1, 255)
    else:
        scan = [search_term_int]
        search_term = ""

    async for dev in enumerate_bus(bus, limit_ids=scan):
        if not search_term or search_term.lower() in repr(dev).lower():
            devices.append(dev)
            print("Discovered %r"%dev)
        else:
            print("Ignoring discovered %s"%dev)

    if not devices:
        print("No matching devices found.")
        print(await bus.exchange(EltakoMessage(0xff, 0x00)))
        return

    print("Now let's see what the devices can do:")

    while True:
        await asyncio.sleep(2)
        for d in devices:
            print("Playing with %r"%d)
            await d.show_off()

            while hasattr(bus, "received") and not bus.received.empty():
                print("Meanwhile, something else happened on the bus as well: %s" % prettify(bus.received.get_nowait()))

@buslocked
async def dump(bus, outfile):
    memfile = MemoryFile()

    async for dev in enumerate_bus(bus):
        try:
            await memfile.add_device(dev)
        except TimeoutError:
            print("Read error, skipping: Device %s announces %d memory but produces timeouts at reading" % (dev, dev.discovery_response.memory_size))
        except Exception:
            pass

    with outfile.open('w') as f:
        memfile.store(f)

@buslocked
async def verify(bus, infile):
    memfile = MemoryFile.load(infile.open())

    delta = 0

    for devno, lines in memfile.items():
        device = await create_busobject(bus, devno)

        current_memory = await device.read_mem()
        for (row, value) in lines.items():
            if current_memory[row] != value:
                delta += 1
                print("Difference in device %s line %d:"%(device, row))
                print("device:", b2a(current_memory[row]))
                print("file:  ", b2a(value))

    if delta:
        sys.exit(1)

@buslocked
async def reprogram(bus, infile):
    memfile = MemoryFile.load(infile.open())

    delta = 0
    seen = 0

    for devno, lines in memfile.items():
        device = await create_busobject(bus, devno)

        current_memory = await device.read_mem()
        for (row, value) in lines.items():
            if current_memory[row] == value:
                seen += 1
            else:
                delta += 1
                await device.write_mem_line(row, value)

    print("Unmodified lines: %d. Modified lines: %d"%(seen, delta))

async def listen(bus:BusInterface, ensure_unlocked):
    if ensure_unlocked:
        await lock_bus(bus)
        await unlock_bus(bus)

    seen_someone_polling = False
    seen_someone_force_polling = False

    while True:
        msg = await bus.received.get()
        msg = prettify(msg)

        if isinstance(msg, EltakoPoll):
            if not seen_someone_polling:
                seen_someone_polling = True
                print("There is a device on the bus that polls for messages.")
            continue

        if isinstance(msg, EltakoPollForced):
            if not seen_someone_force_polling:
                seen_someone_force_polling = True
                print("There is a device on the bus that force-polls for messages.")
            continue

        print(msg)

async def automode(bus):
    for i in range(20):
        try:
            response = await bus.exchange(EltakoBusLock(), EltakoDiscoveryReply)
            if not response.is_fam:
                # typically happens when FAM is just scanning and we get one of
                # its replies back rather than its "OK I'm locked"
                continue
        except TimeoutError:
            continue
        if i == 0:
            print("Bus was locked before")
        found_fam = True
        break
    else:
        print("No FAM present on the bus")
        found_fam = False

    if found_fam:
        try:
            fam = await create_busobject(bus, i)
        except TimeoutError:
            print("Confused: FAM did not allow discovery even though it acknowledged the lcok")
            return

    # Ignore what was seen so far
    while not bus.received.empty():
        bus.received.get_nowait()

    try:
        response = await bus.exchange(EltakoBusUnlock(), EltakoDiscoveryReply)
    except TimeoutError:
        if found_fam:
            print("Confused: FAM did not acknowledge lock release")
            return
    else:
        if not found_fam:
            print("Confused: FAM replied to unlock but not to lock request")

    discovery_seen_for = {}
    spooled_scan_results = {}

    unprocessed_messages = []

    # find out whether it starts scanning, and/or polling
    async def update_discovery():
        while True:
            msg = await bus.received.get()
            msg = prettify(msg)

            if isinstance(msg, EltakoDiscoveryRequest):
                discovery_seen_for[msg.address] = True
                continue

            if isinstance(msg, EltakoDiscoveryReply):
                print("Acknowledging that there's a device:", msg.address, msg)
                spooled_scan_results[msg.reported_address] = msg
                continue

            if isinstance(msg, EltakoPoll) or isinstance(msg, EltakoPollForced):
                print("%d messages queued up unprocessed when polling started" % len(unprocessed_messages))
                print("Polling already started with %s, not expecting any more discovery" % msg)
                unprocessed_messages.append(msg)
                break

            unprocessed_messages.append(msg)

    update_process = asyncio.ensure_future(update_discovery())
    resultcount = -1
    timeout = 3
    while True:
        oldresultcount = resultcount
        resultcount = len(discovery_seen_for) + len(spooled_scan_results)
        if resultcount == oldresultcount:
            # stagnation
            break
        # Wait up to 3 seconds for scanning to get something on, or until it's obviously concluded
        try:
            await asyncio.wait_for(asyncio.shield(update_process), timeout)
        except asyncio.TimeoutError:
            # 3 seconds for the first activity to be on the safe side, but then
            # it should finish swiftly.
            timeout = 1
            continue
        else:
            break
    # This does lose any messages that showed up after the discovery phase, but
    # I'm currently not really interested in that.
    update_process.cancel()

    scancount = len(discovery_seen_for) + sum(s.reported_size - 1 for s in spooled_scan_results.values())

    if scancount == 0:
        print("Nobody is scanning")
    elif scancount == 127:
        print("Bus was scanned in full")
    else:
        print("Bus was only scanned partially?")

    async def poll_watching():
        while True:
            if unprocessed_messages:
                msg = unprocessed_messages.pop(0)
            else:
                msg = await bus.received.get()
            print(prettify(msg))

    await asyncio.Task(poll_watching())

    # NEXT STEP: dissect FAM positions
    # 1: looks like no FAM present on the bus, but then it's sending DiscoveryRequests all through (for bus address teach-in, according to documentation). This mode is particularly odd b/c the FAM acts like if the bus is locked all the time (does it assert HOLD?)
    # 2, 3, 4: FAM found, full scan, and polling starts; in 4 it's forced reads.
    # 5, 6, 7, 8: FAM found, nobody scanning (5-7 according to manual: or it only scans if programmed by the PCT to do so?)
    # 9: similar to 5-8 but potentially odd according to documentation
    # 10: similar to 1 in that the FAM responds to all unlocks

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rawuri", help="URI at which a raw ESP2 resource is exposed")
    p.add_argument("--eltakobus", help="File at which a RS485 Eltako bus can be opened")
    p.add_argument("--baud_rate", default=57600, help="baud rate for transmitter or gateway (FAM15=57600, FGW14-USB=57600, FAM-USB=9600)")
    p.add_argument("--cache", help="Store cachable responses locally", action='store_true')
    p.add_argument("--cachefile", help="File to cache responses at", type=Path)
    p.add_argument("--preread", help="Enumerate bus and read devices' memory before executing the command", action='store_true')
    p.add_argument("--log_level", help="Log level", default="info")
    p.add_argument("--serial_lib_version", default=2)
    subp = p.add_subparsers(metavar="command", dest="command")

    p_enumerate = subp.add_parser("enumerate", help="Explore the bus")
    p_fakefam = subp.add_parser("fakefam", help="Act like a FAM14")
    p_fakefam.add_argument("device", help="Serial device to listen on for bus commands")

    p_send4bs = subp.add_parser("send_raw", help="Send a raw telegram (h_seq/len, org, data, id, status), with bytes as individual hex arguments")
    base16 = functools.partial(int, base=16)
    p_send4bs.add_argument("data", type=base16, nargs=11)

    p_eval = subp.add_parser("eval", help="Display the response to a single message object passed as a Python expression")
    p_eval.add_argument("expr")

    subp.add_parser("lock_bus", help="Lock the bus")
    subp.add_parser("unlock_bus", help="Release the FAM to normal operation")

    p_showoff = subp.add_parser("show_off", help="Run a demo of what is currently known of the bus")
    p_showoff.add_argument("searchterm", nargs="?", default="", help="Bus address or type name to focus on")

    # FIXME allow filtering
    p_dump = subp.add_parser("dump", help="Dump the memory contents of the devices on the bus into a given file")
    p_dump.add_argument("filename", help="File to store the dump in (default: %(default)s)", default="bus.yaml", type=Path, nargs='?')

    p_verify = subp.add_parser("verify", help="Compare the memory contents of the devices with a given dump")
    p_verify.add_argument("filename", help="File to read the dump from (default: %(default)s)", default="bus.yaml", type=Path, nargs='?')

    p_reprogram = subp.add_parser("reprogram", help="Set the memory contents of the devices with a given dump")
    p_reprogram.add_argument("filename", help="File to read the dump from (default: %(default)s)", default="bus.yaml", type=Path, nargs='?')

    p_listen = subp.add_parser("listen", help="Display any messages sent on the bus without sending (not supported on all backends)")
    p_listen.add_argument("--ensure-unlocked", help="Lock and unlock the bus before listening, thus forcing a FAM to re-enumerate", action='store_true')

    subp.add_parser("automode", help="Determine what's on the bus (including FAM mode), report, and listen")

    opts = p.parse_args()

    logging.basicConfig(level=opts.log_level.upper())

    if opts.command is None:
        raise p.error("A command is required.")

    if opts.rawuri is not None and opts.eltakobus is not None:
        raise p.error("--rawuri and --eltakobus are conflicting options.")
    if opts.rawuri is None and opts.eltakobus is None:
        raise p.error("Autodiscovery is not yet implemented, please give --rawuri argument or an --eltakobus.")

    loop = asyncio.new_event_loop()

    if opts.rawuri:
        context = loop.run_until_complete(aiocoap.Context.create_client_context())
        bus = CoAPInterface(context, opts.rawuri)
        cache_rawpart = opts.rawuri.replace('/', '-')
    if opts.eltakobus:
        if opts.serial_lib_version == 2:
            bus = RS485SerialInterfaceV2(opts.eltakobus, baud_rate=int(opts.baud_rate), reconnection_timeout=1, delay_message=0.001)
            bus.start()
            bus.is_serial_connected.wait()
        elif opts.serial_lib_version == 1:
            bus_ready = asyncio.Future(loop=loop)
            bus = RS485SerialInterface(opts.eltakobus, baud_rate=int(opts.baud_rate))
            asyncio.ensure_future(bus.run(loop, conn_made=bus_ready), loop=loop)
            loop.run_until_complete(bus_ready)

        cache_rawpart = opts.eltakobus.replace('/', '-')

    if opts.cache:
        cachefile = opts.cachefile or Path(xdg.BaseDirectory.save_cache_path("eltakotool")) / cache_rawpart
        bus = ReadaheadPickledBusCache(bus, cachefile)

    if opts.preread:
        if not opts.cache:
            print("Warning: Without caching, prereading is not much good.")
        print("Prereading bus...")
        loop.run_until_complete(preread(bus))
        print("done.")

    if opts.command == "enumerate":
        maintask = enumerate_cmd(bus)
    elif opts.command == "fakefam":
        maintask = fakefam(bus, opts.device)
    elif opts.command == "send_raw":
        maintask = send_raw(bus, opts.data)
    elif opts.command == "eval":
        async def maintask(opts):
            msg = eval(opts.expr)
            print("Request: ", prettify(msg))
            response = await bus.exchange(msg)
            print("Response:", response)
        maintask = maintask(opts)
    elif opts.command == "lock_bus":
        maintask = lock_bus(bus)
    elif opts.command == "unlock_bus":
        maintask = unlock_bus(bus)
    elif opts.command == "show_off":
        maintask = show_off(bus, opts.searchterm)
    elif opts.command == 'dump':
        maintask = dump(bus, opts.filename)
    elif opts.command == 'verify':
        if opts.cache:
            print("Warning: verification with cache enabled can be misleading", file=sys.stderr)
        maintask = verify(bus, opts.filename)
    elif opts.command == 'reprogram':
        maintask = reprogram(bus, opts.filename)
    elif opts.command == 'listen':
        maintask = listen(bus, opts.ensure_unlocked)
    elif opts.command == 'automode':
        maintask = automode(bus)
    else:
        raise RuntimeError("Additional command declared but not implemented.")

    maintask = asyncio.Task(maintask, loop=loop)

    try:
        result = loop.run_until_complete(maintask)
    except KeyboardInterrupt as e:
        print("Received keyboard interrupt, cancelling", file=sys.stderr)
        maintask.cancel()
        try:
            loop.run_until_complete(maintask)
        except asyncio.CancelledError:
            pass
        sys.exit(1)

    if result is not None:
        print(result)

    if opts.serial_lib_version == 2:
        bus.stop()

if __name__ == "__main__":
    main()
