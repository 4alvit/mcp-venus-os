"""Standard-library helpers for the isolated workflow checks."""

from contextlib import contextmanager


@contextmanager
def expect_error(error: type[Exception]):
    """Check rejection without adding pytest to the isolated CI environment."""
    try:
        yield
    except error:
        return
    message = "Expected the workflow contract to reject invalid input"
    raise AssertionError(message)
