from .vml import VML, logger
from . import vml_engine
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("vml")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["VML", "logger", "vml_engine"]