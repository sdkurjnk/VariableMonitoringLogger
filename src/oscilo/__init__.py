import sys
import threading
from importlib.metadata import PackageNotFoundError, version

from . import oscilo_engine  # Import eagerly so a missing C extension fails at import time.
from ._core import _Oscilo

try:
    __version__ = version("oscilo")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["register"]

# The package owns exactly one monitor instance; it is created lazily on first
# use so that importing ocilo alone has no side effects (no tracing, no atexit hook).
_instance = None
_instance_lock = threading.Lock()


def register(varName):
    global _instance

    if _instance is None:
        # Double-checked locking so concurrent first calls cannot create two
        # instances, which would reintroduce the multi-instance bug (issue #29).
        with _instance_lock:
            if _instance is None:
                _instance = _Oscilo()

    # Pass the caller's frame explicitly because the instance sits one call deeper.
    _instance.register(varName, sys._getframe(1))
