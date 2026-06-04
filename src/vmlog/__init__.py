from importlib.metadata import PackageNotFoundError, version

from . import vmlog_engine
from .vmlog import VMlog, logger

try:
    __version__ = version("vmlog")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["VMlog", "logger", "vmlog_engine"]