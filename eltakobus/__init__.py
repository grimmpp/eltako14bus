"""
Base definitions for asynchronously accessing devices on an Eltako bus.

The Eltako bus is an RS485 wired installation bus whose protocol mimicks the
EnOcean Serial Protocol 2 (ESP2) but differs in baud rate, access control and
by having implementing additional commands.
"""

from .util import *
from .error import *
from .message import *
from .bus import *
from .serial import *
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
from .diagnostics import *
