class ParseError(ValueError):
    """Raised by ESP2Message and similar's .parse() method when data is unexpected"""
class WriteError(Exception):
    """Raised when a write prcess does not give the expected responses"""
class TimeoutError(Exception):
    """Raised by exchange if the bus timeout is encountered, or a FAM responded with a timeout message."""
class UnrecognizedUpdate(Exception):
    """Raised when interpret_status_update is fed a message which the device does not recognize as being emitted from it."""
class BadFAMMode1(Exception):
    """Raised during locking if a FAM present on the bus scans through the
    available address space continuously (ie. is in mode 1) and thus blocks all
    interaction with the bus."""
