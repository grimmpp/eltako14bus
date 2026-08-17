"""Serializable, side-effect-free diagnostics snapshots.

The adapters in this module only inspect already exposed parser, transport and
gateway state.  Taking a snapshot never consumes a parser error, drains a
queue, opens a connection or sends a telegram.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


DIAGNOSTICS_SCHEMA_VERSION = 1


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    """Convert supported diagnostic values to JSON-native values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if is_dataclass(value):
        return {
            field.name: _json_safe(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


def _freeze(value: Any) -> Any:
    """Defensively copy application-supplied values into immutable containers."""

    if value is None or isinstance(value, (str, int, float, bool, bytes, Enum)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return str(value)


class SerializableSnapshot:
    """Common JSON and dictionary representation for snapshot records."""

    def as_dict(self) -> dict[str, Any]:
        return _json_safe(self)

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(
            self.as_dict(), indent=indent, sort_keys=True, separators=None if indent else (",", ":")
        )


@dataclass(frozen=True, slots=True)
class ErrorSnapshot(SerializableSnapshot):
    """One retained recoverable parser error."""

    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class ParserDiagnosticsSnapshot(SerializableSnapshot):
    """Non-destructive view of an ESP2 or ESP3 stream parser."""

    protocol: str
    parser_type: str
    buffered_bytes: int
    buffered_hex: str
    discarded_bytes: int
    retained_errors: tuple[ErrorSnapshot, ...]
    error_counts: tuple[tuple[str, int], ...]
    max_errors: int | None


@dataclass(frozen=True, slots=True)
class QueueDiagnosticsSnapshot(SerializableSnapshot):
    """Current queue depth without consuming queue entries."""

    name: str
    depth: int | None
    unfinished_tasks: int | None = None


@dataclass(frozen=True, slots=True)
class TransportDiagnosticsSnapshot(SerializableSnapshot):
    """Common state shared by serial and TCP transports."""

    transport_type: str
    active: bool | None
    worker_alive: bool | None
    endpoint: str | None
    auto_reconnect: bool | None
    queues: tuple[QueueDiagnosticsSnapshot, ...]
    parser: ParserDiagnosticsSnapshot | None
    metrics: Any | None = None


@dataclass(frozen=True, slots=True)
class DispatcherDiagnosticsSnapshot(SerializableSnapshot):
    """ESP3 dispatcher counters and current output queue depths."""

    dispatcher_type: str
    counters: tuple[tuple[str, int], ...]
    queues: tuple[QueueDiagnosticsSnapshot, ...]
    closed: bool | None
    failure: str | None


@dataclass(frozen=True, slots=True)
class GatewayDiagnosticsSnapshot(SerializableSnapshot):
    """Top-level snapshot suitable for reports, logs and support bundles."""

    schema_version: int
    captured_at: str
    gateway_type: str
    identity: Mapping[str, Any]
    transport: TransportDiagnosticsSnapshot | None
    dispatcher: DispatcherDiagnosticsSnapshot | None
    metadata: Mapping[str, Any]


def _call_bool(source: Any, name: str) -> bool | None:
    operation = getattr(source, name, None)
    if not callable(operation):
        return None
    try:
        return bool(operation())
    except Exception:
        # Diagnostics must not destabilize the transport being inspected.
        return None


def _queue_snapshot(name: str, queue: Any) -> QueueDiagnosticsSnapshot:
    if queue is None:
        return QueueDiagnosticsSnapshot(name, None, None)
    depth = None
    qsize = getattr(queue, "qsize", None)
    if callable(qsize):
        try:
            depth = int(qsize())
        except Exception:
            # qsize() can be unavailable or platform-specific. A missing
            # metric is safer than allowing diagnostics to affect operation.
            pass
    unfinished = getattr(queue, "unfinished_tasks", None)
    if isinstance(unfinished, int):
        unfinished = int(unfinished)
    else:
        unfinished = None
    return QueueDiagnosticsSnapshot(name, depth, unfinished)


def snapshot_parser(parser: Any, *, protocol: str | None = None) -> ParserDiagnosticsSnapshot:
    """Capture parser state without clearing errors or buffered input."""

    if parser is None:
        raise TypeError("parser is required")
    parser_type = type(parser).__name__
    if protocol is None:
        protocol = "esp3" if "ESP3" in parser_type.upper() else "esp2" if "ESP2" in parser_type.upper() else "unknown"
    buffered = bytes(getattr(parser, "buffered_bytes", b""))
    errors = tuple(getattr(parser, "errors", ()))
    retained = tuple(
        ErrorSnapshot(type(error).__name__, str(error)) for error in errors
    )
    counts = Counter(error.error_type for error in retained)
    discarded = getattr(
        parser, "discarded_bytes", getattr(parser, "discarded_noise_bytes", 0)
    )
    return ParserDiagnosticsSnapshot(
        protocol=str(protocol).lower(),
        parser_type=parser_type,
        buffered_bytes=len(buffered),
        buffered_hex=buffered.hex(),
        discarded_bytes=int(discarded),
        retained_errors=retained,
        error_counts=tuple(sorted(counts.items())),
        max_errors=getattr(parser, "max_errors", None),
    )


def _transport_endpoint(transport: Any) -> str | None:
    filename = getattr(transport, "_filename", None)
    if filename is not None:
        return str(filename)
    host = getattr(transport, "host", None)
    port = getattr(transport, "port", None)
    if host is not None:
        return "%s:%s" % (host, port) if port is not None else str(host)
    return None


def snapshot_transport(transport: Any) -> TransportDiagnosticsSnapshot:
    """Capture public/common transport metrics without changing its state."""

    if transport is None:
        raise TypeError("transport is required")
    queues = []
    for name in ("transmit", "receive", "received"):
        queue = getattr(transport, name, None)
        # ``received`` is often only an adapter around ``receive`` and has no
        # own qsize. Avoid a duplicate unknown entry in that case.
        if queue is not None and (name != "received" or callable(getattr(queue, "qsize", None))):
            queues.append(_queue_snapshot(name, queue))
    parser = getattr(transport, "_frame_parser", None)
    metrics = getattr(transport, "metrics", None)
    metrics_snapshot = None
    snapshot = getattr(metrics, "snapshot", None)
    if callable(snapshot):
        try:
            metrics_snapshot = snapshot()
        except Exception:
            # Diagnostics must remain best-effort if an application supplied
            # a custom metrics collector with a failing snapshot method.
            metrics_snapshot = None
    return TransportDiagnosticsSnapshot(
        transport_type=type(transport).__name__,
        active=_call_bool(transport, "is_active"),
        worker_alive=_call_bool(transport, "is_alive"),
        endpoint=_transport_endpoint(transport),
        auto_reconnect=getattr(transport, "_auto_reconnect", None),
        queues=tuple(queues),
        parser=snapshot_parser(parser) if parser is not None else None,
        metrics=metrics_snapshot,
    )


def snapshot_dispatcher(dispatcher: Any) -> DispatcherDiagnosticsSnapshot:
    """Normalize the native ESP3 dispatcher's immutable counters."""

    if dispatcher is None:
        raise TypeError("dispatcher is required")
    diagnostics = getattr(dispatcher, "diagnostics", None)
    if diagnostics is None:
        counters: tuple[tuple[str, int], ...] = ()
    elif is_dataclass(diagnostics):
        counters = tuple(sorted(
            (field.name, int(getattr(diagnostics, field.name)))
            for field in fields(diagnostics)
        ))
    elif isinstance(diagnostics, Mapping):
        counters = tuple(sorted((str(name), int(value)) for name, value in diagnostics.items()))
    else:
        raise TypeError("dispatcher diagnostics must be a dataclass or mapping")
    queue_names = ("packets", "radio", "events", "responses", "unknown", "errors")
    queues = tuple(
        _queue_snapshot(name, getattr(dispatcher, name))
        for name in queue_names if hasattr(dispatcher, name)
    )
    failure = getattr(dispatcher, "_failure", None)
    return DispatcherDiagnosticsSnapshot(
        dispatcher_type=type(dispatcher).__name__,
        counters=counters,
        queues=queues,
        closed=getattr(dispatcher, "_closed", None),
        failure=str(failure) if failure is not None else None,
    )


def snapshot_gateway(
    gateway: Any,
    *,
    identity: Mapping[str, Any] | None = None,
    dispatcher: Any | None = None,
    metadata: Mapping[str, Any] | None = None,
    captured_at: str | None = None,
) -> GatewayDiagnosticsSnapshot:
    """Build one stable report from a transport/gateway and optional ESP3 dispatcher."""

    if gateway is None:
        raise TypeError("gateway is required")
    return GatewayDiagnosticsSnapshot(
        schema_version=DIAGNOSTICS_SCHEMA_VERSION,
        captured_at=captured_at or _utc_timestamp(),
        gateway_type=type(gateway).__name__,
        identity=_freeze(identity or {}),
        transport=snapshot_transport(gateway),
        dispatcher=snapshot_dispatcher(dispatcher) if dispatcher is not None else None,
        metadata=_freeze(metadata or {}),
    )


__all__ = [
    "DIAGNOSTICS_SCHEMA_VERSION",
    "ErrorSnapshot",
    "ParserDiagnosticsSnapshot",
    "QueueDiagnosticsSnapshot",
    "TransportDiagnosticsSnapshot",
    "DispatcherDiagnosticsSnapshot",
    "GatewayDiagnosticsSnapshot",
    "snapshot_parser",
    "snapshot_transport",
    "snapshot_dispatcher",
    "snapshot_gateway",
]
