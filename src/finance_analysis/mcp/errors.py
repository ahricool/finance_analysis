"""Exception reporting for the private administrator diagnostic tools."""

import traceback


class ReadValidationError(ValueError):
    pass


def format_tool_error(exc: Exception) -> str:
    """Preserve the native message, exception type and complete traceback."""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
