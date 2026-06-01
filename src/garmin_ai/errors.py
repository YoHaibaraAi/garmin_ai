"""Typed errors surfaced by the garmin-ai CLI."""


class GarminAIError(Exception):
    """Base exception with a stable CLI error code."""

    error_code = "UNKNOWN_ERROR"


class AuthRequiredError(GarminAIError):
    """Raised when Garmin token login fails or tokens are missing."""

    error_code = "AUTH_REQUIRED"


class GarminRateLimitedError(GarminAIError):
    """Raised when Garmin appears to rate limit requests."""

    error_code = "GARMIN_RATE_LIMITED"


class FitDownloadError(GarminAIError):
    """Raised when an activity FIT file cannot be downloaded."""

    error_code = "FIT_DOWNLOAD_ERROR"


class FitParseError(GarminAIError):
    """Raised when a FIT file cannot be parsed."""

    error_code = "FIT_PARSE_ERROR"
