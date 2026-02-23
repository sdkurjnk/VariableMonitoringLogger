import sys
import copy
import json
import atexit
from . import vml_engine

class vml:
    history = []

    def __init__(self, var_names, filename="log.jsonl"):
        self.__filename = filename
        self.__var_names = var_names
        self.__last_var_ref = None
        self.__last_var_copy = None
        self.__domain_int = None
        self.__active = True
        self.__tracing_internal = False

        target_frame = sys._getframe(1)
        self.target_frame = target_frame
        
        if self.__var_names in target_frame.f_locals:
            target_var = target_frame.f_locals.get(self.__var_names)
            self.__domain_int = 0 #Local
        elif self.__var_names in target_frame.f_globals:
            target_var = target_frame.f_globals.get(self.__var_names)
            self.__domain_int = 1 #Global
        else:
            print(f"{self.__var_names} is not found.")
            sys.exit(0)

        self.__last_var_ref = target_var
        self.__last_var_copy = copy.deepcopy(target_var)
        
        vml.history.append({
            "name" : self.__var_names,
            "data" : self.__last_var_copy,
            "event" : "init"
        })

        target_frame.f_trace = self._trace_lines
        sys.settrace(self._trace_calls)
        atexit.register(self._final_save)

    def _trace_calls(self, frame, event, arg):
        frame.f_trace_lines = True
        return self._trace_lines

    def _trace_lines(self, frame, event, arg):
        if not self.__active or event != 'line' or self.__tracing_internal:
            return self._trace_lines
        
        self.__tracing_internal = True

        if self.__domain_int == 0: #Local
            if frame is not self.target_frame:
                self.__tracing_internal = False
                return self._trace_lines
        else: #Global
            if frame.f_code.co_filename == __file__:
                self.__tracing_internal = False
                return self._trace_lines

        result = vml_engine.check_variable(
            frame, 
            self.__last_var_ref, 
            self.__last_var_copy, 
            self.__domain_int, 
            self.__var_names
        )

        if result == 1: #When the variable is updated
            current_var = frame.f_locals.get(self.__var_names) if self.__domain_int == 0 else frame.f_globals.get(self.__var_names)
            self.__last_var_ref = current_var
            self.__last_var_copy = copy.deepcopy(current_var)
            vml.history.append({
                "name" : self.__var_names,
                "data" : self.__last_var_copy,
                "event" : "updated"
            })
        elif result is None: #When the variable is deleted
            vml.history.append({
                "name" : self.__var_names,
                "data" : None,
                "event" : "deleted"
            })
            self.__last_var_ref = None
            self.__last_var_copy = None
            self.__active = False
        
        self.__tracing_internal = False
        return self._trace_lines

    def _final_save(self):
        sys.settrace(None)
        if not vml.history: return
        with open(self.__filename, "w", encoding="utf-8") as f:
            for entry in vml.history:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        vml.history.clear()