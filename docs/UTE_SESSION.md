# Generic UTE teach-in sessions

`eltakobus.ute` implements dependency-free EnOcean Universal Teach-In (UTE)
queries and responses. UTE uses RORG `D4` to announce an EEP, manufacturer,
channel count, communication direction and a teach-in or teach-out request.

The implementation is deliberately separate from `eltakobus.teach_in`, which
contains Eltako-specific sender-button telegrams. Parsing a UTE query never
changes device state, stores an association or sends a response.

## Decode a query

```python
from eltakobus.ute import UTERequest

request = UTERequest.from_telegram(radio_telegram)
print(request.profile.eep)          # for example D2-01-0E
print(request.profile.manufacturer) # 11-bit EnOcean manufacturer ID
print(request.channel_count)        # 0xFF means all supported channels
print(request.request_type)
print(request.response_expected)
```

`UTERequest.from_telegram()` requires a `RadioTelegram` with RORG `0xD4` and
exactly seven payload bytes. Reserved request types, non-zero reserved
manufacturer bits and response telegrams are rejected with `UTEParseError`.

`UTEResponse.from_telegram()` provides the corresponding strict response
decoder. Unknown EEPs are retained as numeric RORG, function and type values;
decoding does not depend on the EEP catalog.

The UTE APIs are exported both from their explicit modules and from the
top-level `eltakobus` package. Explicit module imports are recommended because
they make the protocol boundary visible in application code.

## Make an explicit decision

The lowest-level and most auditable workflow is to wait and respond in two
separate calls:

```python
from eltakobus.teach_in_session import UTETeachInSession
from eltakobus.ute import UTEResponseCode

session = UTETeachInSession(
    transport,
    local_sender=bytes.fromhex("FF800001"),
)

request = await session.wait_for_request(timeout=30)

# Check a database, user confirmation, supported EEPs and sender permissions.
decision = UTEResponseCode.TEACH_IN_ACCEPTED
result = await session.respond(request, decision)
```

`respond()` does not send anything when the query says that no response is
expected. It returns a `UTESessionResult` so callers can record whether a
response was sent.

An application can provide a synchronous or asynchronous policy explicitly:

```python
async def policy(request):
    if request.profile.eep not in supported_eeps:
        return UTEResponseCode.EEP_NOT_SUPPORTED
    if request.delete:
        return UTEResponseCode.DELETE_ACCEPTED
    if await user_confirmed(request.sender):
        return UTEResponseCode.TEACH_IN_ACCEPTED
    return UTEResponseCode.NOT_ACCEPTED

result = await session.process_once(
    policy=policy,
    timeout=30,
    decision_timeout=0.45,
)
```

There is no default policy. Returning `None`, raising an exception, cancelling
the task or exceeding `decision_timeout` sends no response. This fail-closed
behavior prevents an incoming radio telegram from enrolling a device by
itself.

Synchronous policies are evaluated in a worker thread so they cannot block the
event loop or bypass `decision_timeout`. Python cannot forcibly stop code that
is already running in a worker thread: after a timeout its return value is
discarded and no response is sent, but the callback itself may finish later.
Policy callbacks should therefore avoid irreversible side effects until their
decision is known. Async policies are cancelled normally on timeout or caller
cancellation.

The UTE specification requires a requested response to be sent within 500 ms
of receiving the query. The default policy timeout is therefore 450 ms, which
leaves a small transport margin. Applications performing slow user approval
should approve first and then ask the sender to repeat its UTE query.

## Transport integration

The session expects:

- `async send(message)`; and
- either `async receive()` or an `asyncio.Queue`-compatible `received.get()`.

Non-UTE telegrams and UTE responses are put into `session.unmatched`.
Malformed UTE messages are both preserved there and recorded in
`session.parse_errors`.

Cancelling `wait_for_request()` cancels the pending queue/receive operation and
does not consume a later telegram. Cancelling `respond()` propagates
cancellation to a cancellable transport send. A physical transport may already
have put bytes on the wire before cancellation is observed, so applications
must not interpret task cancellation as proof that no radio transmission took
place.

The session intentionally has no background receiver. If several consumers
share one physical serial or TCP stream, use one dispatcher as the stream
owner and give the session a dedicated input queue. This avoids races where
two consumers could take each other's messages.

## Building without sending

Models can also be used independently of a session:

```python
response = request.build_response(
    bytes.fromhex("FF800001"),
    UTEResponseCode.TEACH_IN_ACCEPTED,
)
telegram = response.to_telegram()
```

The generated `RadioTelegram` is outgoing, uses the requesting sender as its
ESP3 destination and includes a complete seven-byte ESP3 optional-data
section. Building a model never transmits it.

## Persist an accepted association explicitly

Persistent enrollment is separate from the session and must happen only after
the application has accepted the request and successfully sent the response:

```python
from eltakobus.device_registry import LearnedDeviceRegistry

registry = LearnedDeviceRegistry.load("learned-devices.json")
result = await session.respond(request, decision)
if result.sent:
    registry.enroll(request, metadata={"room": "office"}, replace=True)
    registry.save("learned-devices.json")
```

The registry stores the sender, UTE profile, channel count, communication
direction and JSON metadata. It never listens, sends, or enrolls a device while
parsing. Delete requests are rejected by `enroll`; use `remove(sender,
channel_count)` only after an explicit, application-approved teach-out.

Writes use a temporary file and atomic replacement. The JSON schema is
versioned and invalid or unknown schemas fail closed.

## Current limits

- The module implements EEP-based UTE query/response command IDs `0x0` and
  `0x1`; Generic Profiles teach-in, Smart Ack and remote management are
  separate protocols.
- It does not allocate sender IDs or alter actuator memory. Those actions
  belong in an application policy or a future safe configuration transaction.
- It does not verify that an announced EEP exists in the local catalog.
- Success response codes are checked against explicit teach-in and deletion
  requests. A `NOT_SPECIFIC` request may validly receive either success code.
- Secure teach-in and encrypted radio telegrams are outside this slice.
- A shared physical receive stream still needs the roadmap's typed ESP3
  dispatcher; the session only defines its narrow transport boundary.

The wire layout follows the EnOcean EEP specification's EEP Teach-In Query
and EEP Teach-In Response definitions. The `kipe/enocean` and OpenOcean
implementations were used only as interoperability references; this module is
an independent, immutable implementation.
