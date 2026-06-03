from importlib.metadata import PackageNotFoundError, version

from . import vml_engine
from .vml import VML, logger

try:
    __version__ = version("vml")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["VML", "logger", "vml_engine"]