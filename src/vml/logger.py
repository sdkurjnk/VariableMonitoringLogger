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
        self.last_var = None
        self.domain = None
        self._active = True

        target_frame = sys._getframe(1)
        target_frame.f_trace = self._trace_lines

        if (self.var_names in target_frame.f_globals):
            self.last_var = copy.deepcopy(target_frame.f_globals[self.var_names])
            self.domain = "G"
        elif (self.var_names in target_frame.f_code.co_varnames):
            self.last_var = copy.deepcopy(target_frame.f_locals[self.var_names])
            self.domain = "L"
        else:
            print("There is no such variable.")
            sys.exit(1)
        
        vml.history.append({
            "name" : self.var_names,
            "data" : copy.deepcopy(self.last_var),
            "event" : "init"
            })

        sys.settrace(self._trace_calls)
        atexit.register(self._final_save)

    def _trace_calls(self, frame, event, arg):
        frame.f_trace_lines = True
        return self._trace_lines

    def _trace_lines(self, frame, event, arg):
        if (self._active == False):
            return None

        if event != 'line': return self._trace_lines

        result = vml_engine.check_variable(frame, self.last_var, self.var_names, self.domain)

        if (result == 1):
            current_val = frame.f_locals.get(self.var_names) if self.domain == "L" else frame.f_globals.get(self.var_names)

            if (current_val != self.last_var):
                self.last_var = copy.deepcopy(current_val)

                vml.history.append({
                    "name" : self.var_names,
                    "data" : copy.deepcopy(self.last_var),
                    "event" : "updated"
                })

        elif (result is None):
            if (self.last_var != None):
                vml.history.append({
                    "name" : self.var_names,
                    "data" : None,
                    "event" : "deleted"
                })

                self.last_var = None

        return self._trace_lines

    def _final_save(self):
        if not vml.history: return
        
        with open(self.filename, "w", encoding="utf-8") as f:
            for entry in vml.history:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        
        sys.settrace(None)
        vml.history.clear()
    
    def stop(self):
        if not self._active:
            return

        vml.history.append({
            "name" : self.var_names,
            "data" : None,
            "event" : "Monitering was stopped."
        })

        self._active = False