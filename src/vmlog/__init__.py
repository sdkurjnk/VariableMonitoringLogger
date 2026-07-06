import sys
import threading
from importlib.metadata import PackageNotFoundError, version

from . import vmlog_engine
from .vmlog import _vmlog

try:
    __version__ = version("vmlog")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["logRegister"]

_instance = None
_instance_lock = threading.Lock()

def logRegister(varName):
    global _intance

    if _intance is None:
        with _instance_lock:
            if _intance is None:
                _instance = _vmlog()

    _instance.register(varName, sys._getframe(1))