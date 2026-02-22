from .logger import vml as logger
from importlib.metadata import version, PackageNotFoundError

try:
    from . import vml_engine
except ImportError:
    vml_engine = None

try:
    __version__ = version("vml")
except PackageNotFoundError:
    __version__ = "unknown"