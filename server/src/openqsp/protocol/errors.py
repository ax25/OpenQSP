"""Internal exceptions raised by the future OpenQSP protocol codec."""


class ProtocolError(Exception):
    """Base class for internal protocol codec failures."""


class ProtocolDecodeError(ProtocolError):
    """A frame could not be decoded."""


class ProtocolEncodeError(ProtocolError):
    """A model could not be encoded."""


class UnsupportedVersionError(ProtocolDecodeError):
    """A frame uses an unsupported protocol version."""


class UnknownOperationError(ProtocolDecodeError):
    """A frame contains an unknown operation code."""


class InvalidFieldError(ProtocolError):
    """A protocol field has an invalid value or representation."""


class FieldTooLongError(InvalidFieldError):
    """A text field exceeds its domain-defined UTF-8 byte limit."""

    def __init__(self, field: str, minimum: int, maximum: int) -> None:
        self.field = field
        self.minimum = minimum
        self.maximum = maximum
        super().__init__(
            f"{field} must contain between {minimum} and {maximum} UTF-8 bytes"
        )


class PayloadLengthError(ProtocolDecodeError):
    """A frame payload does not have its declared or required length."""
