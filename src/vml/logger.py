import sys
import copy
import json
import atexit
from . import vml_engine

class vml:
    history = []

    def __init__(self, var_names, filename="log.jsonl"):
        self.filename = filename
        self.var_names = var_names
        self.last_var_ref = None
        self.last_var_copy = None
        self.domain_int = None
        self._active = True

        target_frame = sys._getframe(1)
        self.target_frame = target_frame
        
        if self.var_names in target_frame.f_locals:
            target_var = target_frame.f_locals.get(self.var_names)
            self.domain_int = 0
        elif self.var_names in target_frame.f_globals:
            target_var = target_frame.f_globals.get(self.var_names)
            self.domain_int = 1
        else:
            sys.exit(1)

        self.last_var_ref = target_var
        self.last_var_copy = copy.deepcopy(target_var)
        
        vml.history.append({
            "name" : self.var_names,
            "data" : self.last_var_copy,
            "event" : "init"
        })

        target_frame.f_trace = self._trace_lines
        sys.settrace(self._trace_calls)
        atexit.register(self._final_save)

    def _trace_calls(self, frame, event, arg):
        frame.f_trace_lines = True
        return self._trace_lines

    def _trace_lines(self, frame, event, arg):
        if not self._active or event != 'line':
            return self._trace_lines

        if self.domain_int == 0:
            if frame is not self.target_frame:
                return self._trace_lines
        else:
            if frame.f_code.co_filename == __file__:
                return self._trace_lines

        result = vml_engine.check_variable(
            frame, 
            self.last_var_ref, 
            self.last_var_copy, 
            self.domain_int, 
            self.var_names
        )

        if result == 1:
            current_var = frame.f_locals.get(self.var_names) if self.domain_int == 0 else frame.f_globals.get(self.var_names)
            self.last_var_ref = current_var
            self.last_var_copy = copy.deepcopy(current_var)
            vml.history.append({
                "name" : self.var_names,
                "data" : self.last_var_copy,
                "event" : "updated"
            })
        elif result is None:
            vml.history.append({
                "name" : self.var_names,
                "data" : None,
                "event" : "deleted"
            })
            self.last_var_ref = None
            self.last_var_copy = None
            self._active = False
            
        return self._trace_lines

    def _final_save(self):
        sys.settrace(None)
        if not vml.history: return
        with open(self.filename, "w", encoding="utf-8") as f:
            for entry in vml.history:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        vml.history.clear()