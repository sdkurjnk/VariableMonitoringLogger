LOCAL = 0
GLOBAL = 1
ENCLOSING = 2
BUILTIN = 3
NOT_FOUND = -1


class ScopeResolver:
    def resolve(self, frame, var_name):
        code = frame.f_code

        # Statically declared local (co_cellvars covers locals captured by inner functions).
        if var_name in code.co_varnames or var_name in code.co_cellvars:
            # A declared local shadows outer scopes even while unbound (deleted or
            # not yet assigned), so report NOT_FOUND instead of falling through.
            if var_name in frame.f_locals:
                return LOCAL, frame.f_locals.get(var_name)
            return NOT_FOUND, None

        # Free variable captured from an enclosing function scope.
        if var_name in code.co_freevars:
            if var_name in frame.f_locals:
                return ENCLOSING, frame.f_locals.get(var_name)
            return NOT_FOUND, None

        if var_name in frame.f_globals:
            return GLOBAL, frame.f_globals.get(var_name)

        if var_name in frame.f_builtins:
            return BUILTIN, frame.f_builtins.get(var_name)

        return NOT_FOUND, None