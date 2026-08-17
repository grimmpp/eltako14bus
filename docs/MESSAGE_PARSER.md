# ESP2 message classification

`eltakobus.message.classify_message()` selects the most specific legacy ESP2
message class from a complete serialized frame without trying every decoder
and catching `ParseError` exceptions.

```python
from eltakobus.message import classify_message, prettify

message_class = classify_message(raw_frame)
if message_class is None:
    print("invalid or unsupported ESP2 frame")
else:
    message = message_class.parse(raw_frame)

# Compatibility helper for diagnostic display:
message = prettify(legacy_message)
```

Classification validates the ESP2 preamble, fixed frame length and checksum,
then uses the stable `h_seq` and ORG bytes. It also distinguishes RPS, 1BS,
regular 4BS and Variation 2 4BS teach-in messages, plus Eltako TCT/RMT
wrappers and fixed commands. A valid but unknown family falls back to
`ESP2Message`; an invalid frame returns `None`.

The classifier does not replace semantic validation. The selected class still
validates reserved bits, fixed payload markers and message-specific fields in
its existing `parse()` method. `prettify()` calls only that selected parser;
when semantic validation fails it returns the original lossless message rather
than probing unrelated decoders.

Applications that already know the expected message type should continue to
call that class's `parse()` method directly. The classifier is intended for
debugging, mixed-message receive streams and dispatch code that needs a stable
type decision before decoding.
