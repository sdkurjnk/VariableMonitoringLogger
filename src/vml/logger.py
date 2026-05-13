import sys
import copy
import json
import atexit
from . import vml_engine

class LogEntry:
    def __init__(self, name, data, event):
        self.name = name
        self.data = data
        self.event = event

    def to_dict(self):
        return {"name": self.name, "data": self.data, "event": self.event}

class HistoryBuffer:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(HistoryBuffer, cls).__new__(cls)
            cls._instance._history = []
        return cls._instance

    def append(self, name, data, event):
        self._history.append(LogEntry(name, data, event))

    def get(self):
        return self._history

    def clear(self):
        self._history.clear()

class FileWriter:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FileWriter, cls).__new__(cls)
        return cls._instance

    def write(self, filename, history):
        with open(filename, 'w', encoding='utf-8') as f:
            for entry in history:
                f.write(json.dumps(entry.to_dict()) + '\n')

class ScopeResolver:
    @staticmethod
    def resolve(frame, var_name):
        if var_name in frame.f_locals:
            return 1, frame.f_locals[var_name]
        elif var_name in frame.f_globals:
            return 0, frame.f_globals[var_name]
        return -1, None 
    
class VariableTracker:
    def __init__(self, var_name):
        self.var_name = var_name
        self._last_ref = None
        self._last_copy = None
        self._active = True
        self._domain = -1
        
    def _initialize_state(self, frame):
        domain, val = ScopeResolver.resolve(frame, self.var_name)
        if domain != -1:
            self._domain = domain
            self._last_ref = val
            try:
                self._last_copy = copy.deepcopy(val)
            except Exception:
                self._last_copy = val

    def check(self, frame):
        if not self._active:
            return

        if self._domain == -1:
            self._initialize_state(frame)
            return

        result = variable_engine.check_variable(
            frame, self._last_ref, self._last_copy, self._domain, self.var_name
        )

        buffer = HistoryBuffer()
        
        if result == 1:
            _, current_val = ScopeResolver.resolve(frame, self.var_name)
            buffer.append(self.var_name, current_val, "updated")
            self._last_ref = current_val
            try:
                self._last_copy = copy.deepcopy(current_val)
            except Exception:
                self._last_copy = current_val
                
        elif result is None:
            buffer.append(self.var_name, None, "deleted")
            self._active = False
class TraceDispatcher:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TraceDispatcher, cls).__new__(cls)
            cls._instance._trackers = []
            cls._instance._is_tracing = False
        return cls._instance

    @classmethod
    def get_instance(cls):
        return cls()

    def register(self, tracker):
        self._trackers.append(tracker)
        if not self._is_tracing:
            sys.settrace(self._trace_calls)
            self._is_tracing = True

    def unregister(self, tracker):
        if tracker in self._trackers:
            self._trackers.remove(tracker)
        if not self._trackers and self._is_tracing:
            sys.settrace(None)
            self._is_tracing = False

    def _trace_calls(self, frame, event, arg):
        if event != 'call':
            return
        return self._trace_lines

    def _trace_lines(self, frame, event, arg):
        if event not in ('line', 'return'):
            return self._trace_lines
        
        for tracker in self._trackers:
            tracker.check(frame)
            
        return self._trace_lines

class VML:
    _is_exit_registered = False

    def __init__(self, var_names, filename="vml_log.jsonl"):
        self.fileName = filename
        
        if isinstance(var_names, str):
            var_names = [var_names]

        dispatcher = TraceDispatcher.get_instance()

        for name in var_names:
            tracker = VariableTracker(name)
            dispatcher.register(tracker)

        if not VML._is_exit_registered:
            atexit.register(self._final_save)
            VML._is_exit_registered = True

    def _final_save(self):
        sys.settrace(None)
        
        buffer = HistoryBuffer()
        writer = FileWriter()
        history = buffer.get()
        
        if history:
            writer.write(self.fileName, history)
            
        buffer.clear()