class ScopeResolver:
    def resolve(self, frame, var_name):
        if var_name in frame.f_locals:
            return 0, frame.f_locals.get(var_name)
        
        if var_name in frame.f_globals:
            return 1, frame.f_globals.get(var_name)
        
        return -1, None