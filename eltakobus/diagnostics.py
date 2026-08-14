"""Reusable, hardware-independent bus diagnostics.

The functions are deliberately small orchestration primitives.  They do not assume Home
Assistant entities and can therefore be used by command-line tools, replay tests, and hardware
test runners alike.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict

from .error import TimeoutError
from .message import EltakoDiscoveryReply, EltakoDiscoveryRequest


@dataclass
class DiagnosticResult:
    address: int
    discovered: bool
    elapsed: float | None = None
    error: str | None = None

    def as_dict(self):
        return asdict(self)


async def probe_devices(bus, addresses, *, timeout_retries=1) -> list[DiagnosticResult]:
    """Discover each address and record timing; timeouts become results, not process errors."""
    results = []
    for address in addresses:
        started = time.monotonic()
        try:
            await bus.exchange(EltakoDiscoveryRequest(address), EltakoDiscoveryReply,
                               retries=timeout_retries)
        except TimeoutError:
            results.append(DiagnosticResult(address, False, time.monotonic() - started, "timeout"))
        except Exception as exc:
            results.append(DiagnosticResult(address, False, time.monotonic() - started, str(exc)))
        else:
            results.append(DiagnosticResult(address, True, time.monotonic() - started))
    return results


async def read_memory_test(bus, address, *, memory_size=255) -> dict:
    """Read a complete device memory image and return a serializable report."""
    started = time.monotonic()
    try:
        rows = await bus.read_mem(address, known_memory_size=memory_size)
    except Exception as exc:
        return {"address": address, "ok": False, "elapsed": time.monotonic() - started,
                "error": str(exc)}
    return {"address": address, "ok": True, "elapsed": time.monotonic() - started,
            "rows": len(rows), "bytes": sum(len(row) for row in rows)}
