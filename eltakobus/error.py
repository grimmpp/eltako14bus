class ParseError(ValueError):
    """Raised by ESP2Message and similar's .parse() method when data is unexpected"""
class WriteError(Exception):
    """Raised when a write prcess does not give the expected responses"""
class TimeoutError(Exception):
    """Raised by exchange if the bus timeout is encountered, or a FAM responded with a timeout message."""
class NotImplementedError(Exception):
    """Raised when the subclass did not override the function."""
class WrongOrgError(Exception):
    """Raised when the org of the message is not the same as the expected org."""
