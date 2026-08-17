# Native ESP2 framing

`eltakobus.esp2_frame.ESP2FrameParser` handles the byte stream shared by the
ESP2 TCP gateway and threaded RS485 interface. An ESP2 frame is always 14
bytes:

```text
A5 5A | 11 body bytes | modulo-256 checksum(body)
```

The parser accepts arbitrary read boundaries, several frames in one read and
noise between frames. It retains a split `A5` preamble, validates the complete
frame before returning it, and advances one byte after a checksum failure so a
later valid frame can be recovered.

```python
from eltakobus.esp2_frame import ESP2FrameParser
from eltakobus.message import ESP2Message, prettify

parser = ESP2FrameParser()
for chunk in incoming_bytes:
    for raw in parser.feed(chunk):
        message = prettify(ESP2Message.parse(raw))
        handle(message)

for error in parser.pop_errors():
    logger.warning("Discarded invalid ESP2 frame: %s", error)
```

The framing layer returns raw validated bytes rather than selecting a message
subclass. This keeps framing, message interpretation, echo suppression and
request/response matching independent. Existing transport classes and message
constructors remain compatible.
