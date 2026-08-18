import sys
import threading
from importlib.metadata import PackageNotFoundError, version

from . import oscilo_engine  # C 확장이 없으면 import 시점에 바로 실패하도록 즉시 import.
from ._core import _Oscilo

try:
    __version__ = version("oscilo")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["register"]

# monitor 인스턴스는 하나만 두고 첫 사용 때 지연 생성한다. import만으로는
# 부작용(트레이싱·atexit 훅)이 없게 하려는 것.
_instance = None
_instance_lock = threading.Lock()


def register(varName):
    global _instance

    if _instance is None:
        # 동시 첫 호출이 인스턴스를 둘 만들지 않도록 double-checked locking. (이슈 #29)
        with _instance_lock:
            if _instance is None:
                _instance = _Oscilo()

    # 인스턴스가 한 단계 더 깊이 있으므로 호출자 frame을 명시적으로 넘긴다.
    _instance.register(varName, sys._getframe(1))
