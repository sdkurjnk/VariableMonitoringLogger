import sys
import copy
import json
import atexit
from . import vml_engine

class vml:
    __history = []

    @classmethod
    def _add_history_entry(cls, entry):
        cls.__history.append(entry)

    @classmethod
    def _get_history(cls):
        return cls.__history

    @classmethod
    def _clear_history(cls):
        cls.__history.clear()

    def __init__(self, var_names, filename="log.jsonl"):
        self.__filename = filename
        self.__var_names = var_names
        self.__last_var_ref = None
        self.__last_var_copy = None
        self.__domain_int = None
        self.__active = True
        self.__tracing_internal = False

        self.__target_frame = sys._getframe(1)
        
        if self.__var_names in self.__target_frame.f_locals:
            target_var = self.__target_frame.f_locals.get(self.__var_names)
            self.__domain_int = 0 #Local
        elif self.__var_names in self.__target_frame.f_globals:
            target_var = self.__target_frame.f_globals.get(self.__var_names)
            self.__domain_int = 1 #Global
        else:
            print(f"{self.__var_names} is not found.")
            sys.exit(0)

        self.__last_var_ref = target_var
        self.__last_var_copy = copy.deepcopy(target_var)
        
        vml._add_history_entry({
            "name" : self.__var_names,
            "data" : self.__last_var_copy,
            "event" : "init"
        }) 

        self.__target_frame.f_trace = self._trace_lines
        sys.settrace(self._trace_calls)
        atexit.register(self._final_save)

    def _trace_calls(self, frame, event, arg):
        frame.f_trace_lines = True
        return self._trace_lines

    def _trace_lines(self, frame, event, arg):
        if not self.__active or event != 'line':
            return self._trace_lines

        if self.__tracing_internal:
            return self._trace_lines
        self.__tracing_internal = True

        if self.__domain_int == 0:
            if frame is not self.__target_frame:
                self.__tracing_internal = False
                return self._trace_lines
        else:
            if frame.f_code.co_filename == __file__:
                self.__tracing_internal = False
                return self._trace_lines

        if vml_engine is None:
            raise RuntimeError("vml_engine is not loaded. Cannot monitor variables effectively.")

        result = vml_engine.check_variable(
            frame, 
            self.__last_var_ref, 
            self.__last_var_copy, 
            self.__domain_int, 
            self.__var_names
        )

        if result == 1:
            current_var = frame.f_locals.get(self.__var_names) if self.__domain_int == 0 else frame.f_globals.get(self.__var_names)
            self.__last_var_ref = current_var
            self.__last_var_copy = copy.deepcopy(current_var) 
            vml._add_history_entry({
                "name" : self.__var_names,
                "data" : self.__last_var_copy,
                "event" : "updated"
            })
        elif result is None:
            vml._add_history_entry({ # Using class method
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
        if not vml._get_history(): return
        with open(self.__filename, "w", encoding="utf-8") as f:
            for entry in vml._get_history():
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        vml._clear_history()