import atexit
import sys

from .FileWriter import FileWriter
from .HistoryBuffer import HistoryBuffer
from .TraceDispatcher import TraceDispatcher


class Oscilo:
    def __init__(self, fileName="oscilo.jsonl"):
        self.fileName = fileName
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)
        self.fileWriter = FileWriter()
        self._saved = False

        # 수동 정리 없이도 종료 시 저장되도록 등록.
        atexit.register(self.finalSave)

    def register(self, varName, frame=None):
        # dispatcher가 변수를 해석하도록 호출자 frame을 넘긴다.
        if frame is None:
            frame = sys._getframe(1)

        self.dispatcher.register(varName, frame=frame)

    def finalSave(self):
        # 수동 호출과 atexit 양쪽에서 불릴 수 있어 멱등하게 유지한다.
        if self._saved:
            return

        self._stop_tracking()
        self._write_history()
        self._saved = True

    def _stop_tracking(self):
        # 저장 중 추가 이벤트가 안 남도록 먼저 트레이싱을 멈춘다.
        self.dispatcher.stop()

    def _write_history(self):
        history = self.buffer.getHistory()

        # 기록이 없으면 파일을 만들지 않는다.
        if not history:
            return

        self.fileWriter.write(self.fileName, history)
