"""Exceptions for the Tapo L630 integration."""


class TapoError(Exception):
    """Base Tapo communication error."""


class TapoAuthenticationError(TapoError):
    """Raised when Tapo credentials are rejected."""


class TapoConnectionError(TapoError):
    """Raised when the bulb cannot be reached."""


class TapoSessionError(TapoError):
    """Raised when the encrypted session has expired."""


class UnsupportedDeviceError(TapoError):
    """Raised when the configured device is not an L630."""
