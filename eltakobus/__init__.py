"""
Base definitions for asynchronously accessing devices on an Eltako bus.

The Eltako bus is an RS485 wired installation bus whose protocol mimicks the
EnOcean Serial Protocol 2 (ESP2) but differs in baud rate, access control and
by having implementing additional commands.
"""

from .util import *
from .error import *
from .message import *
from .radio import *
from .vld import *
from .esp3_frame import *
from .esp2_frame import *
from .esp3_packet import *
from .esp3_dispatcher import *
from .eep_schema import *
from .ute import *
from .teach_in_session import *
from .device_registry import *
from .memory_session import *
from .diagnostic_snapshot import *
from .transport_metrics import *
from .bus import *
from .esp2_gateway import *
from .esp3 import *
# Keep transport/tool extras optional: passive gateway scanning and message parsing should also
# work in a minimal installation without aiocoap or PyYAML.
try:
    from .coap import *
except ImportError:  # pragma: no cover - exercised in minimal installations
    pass
try:
    from .device import *
except ImportError:  # pragma: no cover - exercised in minimal installations
    pass
from . import locking
from . import eep

# Optional protocol-neutral discovery and diagnostics helpers.  Importing these modules does
# not open hardware; applications decide when a scan or probe is safe.
from .const import *
from .gateway_scan import *
from .gateway_identity import *
from .lan_discovery import *
from .diagnostics import *
from .device_catalog import *
from .teach_in import *


# Serial support is an optional extra.  Keep the dependency-free core importable while
# preserving the historical package-level names for installations that have the extra.
_SERIAL_EXPORTS = frozenset({
    "RS485SerialInterfaceV2",
    "RS485SerialInterface",
})

# Preserve the historical wildcard exports when the optional serial extra is
# installed.  In a minimal installation this import is intentionally skipped;
# explicit attribute access below still provides the actionable lazy import.
try:  # pragma: no cover - availability is environment-dependent
    from .serial import RS485SerialInterfaceV2, RS485SerialInterface
except ImportError:
    pass


def __getattr__(name):
    if name in _SERIAL_EXPORTS:
        from . import serial as serial_transport
        return getattr(serial_transport, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | _SERIAL_EXPORTS)
