"""ws_api package initializer: expose public API and exceptions."""

from __future__ import annotations

from .exceptions import (
    CurlException,
    LoginFailedException,
    ManualLoginRequired,
    OTPRequiredException,
    UnexpectedException,
    WSApiException,
)
from .session import WSAPISession
from .wealthsimple_api import WealthsimpleAPI

__all__ = [
    'WealthsimpleAPI',
    'WSAPISession',
    'ManualLoginRequired',
    'OTPRequiredException',
    'WSApiException',
    'LoginFailedException',
    'CurlException',
    'UnexpectedException',
]
