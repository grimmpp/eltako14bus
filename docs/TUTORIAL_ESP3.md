# ESP3 tutorial: decode native radio frames

The native ESP3 layer separates stream framing, semantic decoding and
transport. It does not require the historic `enocean` package.

```python
from eltakobus.esp3_frame import ESP3FrameParser
from eltakobus.esp3_packet import decode_esp3_packet
from eltakobus.radio import RadioTelegram

parser = ESP3FrameParser()
for frame in parser.feed(raw_bytes_from_your_transport):
    packet = decode_esp3_packet(frame)
    if isinstance(packet, RadioTelegram):
        print(packet.rorg, packet.sender.hex(), packet.payload.hex())
for error in parser.pop_errors():
    print("ignored malformed frame", error)
```

The parser accepts arbitrary stream chunks, validates both CRCs and
resynchronizes after noise. Unknown packet types remain lossless. For command
transports, place `ESP3Dispatcher` above a frame transport that provides async
`send(frame)` and `receive()`:

```python
from eltakobus.esp3_dispatcher import ESP3Dispatcher
from eltakobus.esp3_packet import ESP3Command

async with ESP3Dispatcher(frame_transport) as dispatcher:
    response = await dispatcher.execute(ESP3Command(0x08), timeout=1)
```

For an offline executable reading hexadecimal chunks from stdin, see
[`examples/esp3_decode_stream.py`](../examples/esp3_decode_stream.py).

For a read-only USB serial reader, use
[`examples/esp3_usb_stream.py`](../examples/esp3_usb_stream.py):

```sh
python -m pip install 'eltako14bus[serial]'
python -m examples.esp3_usb_stream /dev/ttyUSB0 --baudrate 57600
```

On macOS, replace the device with the corresponding `/dev/cu.*` path. The
example reads arbitrary USB chunks, lets `ESP3FrameParser` handle framing and
CRC recovery, and prints decoded native packet objects. It never transmits.

If `serial_for_url` is missing, the environment contains an incomplete or
wrong package named `serial`. Repair the virtual environment with:

```sh
python -m pip install --force-reinstall pyserial
```

Do not install the unrelated package named `serial`; the library requires
`pyserial`.
