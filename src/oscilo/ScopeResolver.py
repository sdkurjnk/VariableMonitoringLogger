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

    def resolve_cell(self, frame, var_name):
        """free variable을 뒷받침하는 실제 closure `cell` 객체를 해석한다.

        `sys.settrace`의 콜백은 항상 frame 객체만 넘겨주며, 맨 frame만으로는
        어떤 공식 Python/C API로도 closure cell을 노출시킬 방법이 없다
        (실측 확인: `frame.f_locals`, `gc.get_referents(frame)`, 그리고 안정
        C-API인 `PyFrame_GetVar`조차 전부 *역참조된 값*만 반환하고 cell 자체는
        반환하지 않는다). cell은 오직 function 객체의 `__closure__`를 통해서만
        접근 가능하므로, 이 resolver는 직접 호출자(caller)의 frame
        (`frame.f_back`)에서 다음 조건을 만족하는 콜러블을 찾는다: (a) 추적 중인
        frame과 같은 code 객체를 쓰고, (b) 해당 인덱스의 closure cell이 현재
        추적 중인 frame의 실제 값과 일치한다.

        이것은 보장이 아니라 휴리스틱이다. 호출 시점에 caller의 locals/globals
        안에서 평범한 이름으로 접근 가능하지 않았던 콜러블(예: `outer()()`처럼
        이름에 바인딩되지 않은 즉시 호출, 또는 속성/딕셔너리 접근을 통해 호출된
        콜백)은 cell을 해석하지 못한다. `resolve_cell`을 호출하는 쪽은 `None`을
        "소유권을 판단할 수 없음"으로 취급하고 그에 맞게 fallback해야 한다.

        `resolve`(항상 답을 주는 전체함수)와 달리, 이것은 best-effort로
        `cell | None`을 돌려주며 caller frame까지 뒤진다는 점에 유의한다.
        """
        code = frame.f_code

        if var_name not in code.co_freevars:
            return None

        index = code.co_freevars.index(var_name)
        caller = frame.f_back

        if caller is None:
            return None

        current_value = frame.f_locals.get(var_name)
        candidates = list(caller.f_locals.values()) + list(caller.f_globals.values())

        for candidate in candidates:
            cell = self._match_candidate(candidate, code, index, current_value)
            if cell is not None:
                return cell

        return None

    def _match_candidate(self, candidate, code, index, current_value):
        # `self.method` 형태의 콜백도 처리할 수 있도록 bound method를 풀어낸다.
        func = getattr(candidate, "__func__", candidate)

        if getattr(func, "__code__", None) is not code:
            return None

        closure = getattr(func, "__closure__", None)
        if not closure or len(closure) <= index:
            return None

        cell = closure[index]

        # 같은 code 객체를 공유하는 서로 다른 여러 closure가 caller의
        # namespace에 함께 존재할 수 있다(예: 서로 다른 이름으로 저장된
        # 두 개의 별도 `outer()` 결과). cell이 현재 추적 중인 frame이
        # 실행 중인 바로 그 객체를 담고 있는지 확인해서 구분한다.
        try:
            cell_value = cell.cell_contents
        except ValueError:
            # cell이 아직 바인딩되지 않음(드문 타이밍 엣지 케이스); 일치 여부를 확인할 수 없다.
            return None

        if cell_value is not current_value:
            return None

        return cell