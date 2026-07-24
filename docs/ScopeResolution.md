# 스코프 해석

변수 이름 하나가 어느 스코프에 속하는지 판정하는 방식과, ENCLOSING 변수를 다루기 위해 감수한 타협을 정리한다.

관련 코드: `ScopeResolver.resolve`, `TraceDispatcher._ClosureResolver`

---

## LEGB 판정 순서

`ScopeResolver.resolve()`는 프레임과 이름을 받아 도메인과 현재 값을 돌려준다. 판정은 **런타임 딕셔너리가 아니라 코드 객체의 정적 정보**를 먼저 본다.

```
co_varnames / co_cellvars 에 있음  → LOCAL
co_freevars 에 있음                → ENCLOSING
f_globals 에 있음                  → GLOBAL
f_builtins 에 있음                 → BUILTIN
그 외                              → NOT_FOUND
```

`co_cellvars`가 LOCAL에 포함되는 이유는, 내부 함수에 캡처되는 변수라도 **선언된 프레임 입장에서는 지역 변수**이기 때문이다. 그 변수를 자유 변수로 참조하는 쪽(내부 함수)에서만 ENCLOSING이 된다.

## 선언된 지역 변수는 미바인딩 상태에서도 외부를 가리지 않는다

가장 중요한 판정 규칙이다. 이름이 `co_varnames`에 있는데 아직 `f_locals`에 없으면, 상위 스코프로 내려가지 않고 `NOT_FOUND`를 반환한다.

```python
if var_name in code.co_varnames or var_name in code.co_cellvars:
    if var_name in frame.f_locals:
        return LOCAL, frame.f_locals.get(var_name)
    return NOT_FOUND, None
```

파이썬의 실제 동작을 그대로 반영한 것이다. 함수 안에 대입문이 하나라도 있으면 그 이름은 함수 전체에서 지역 변수이며, 할당 이전에 접근하면 전역 값이 보이는 게 아니라 `UnboundLocalError`가 난다. 삭제된 뒤에도 마찬가지다.

여기서 상위 스코프로 폴백했다면, **동명의 전역 변수 값을 지역 변수의 값인 것처럼 기록하는** 오류가 생긴다. 값이 존재하지 않는 구간을 정직하게 `NOT_FOUND`로 남기는 편이 맞다.

## ENCLOSING의 소유권 문제

ENCLOSING 변수는 다른 두 도메인과 성격이 다르다. **값의 소유자가 프레임이 아니라 클로저 셀이다.**

```python
def outer():
    n = 0
    def inner():
        nonlocal n
        n += 1
    return inner
```

`inner` 프레임은 매 호출마다 새로 생기고 사라지지만 `n`은 셀에 남아 이어진다. `outer`가 반환된 뒤에도 살아 있고, `outer()`를 두 번 호출하면 같은 코드 객체를 공유하는 **서로 다른 셀 두 개**가 생긴다.

따라서 identity와 값 이력을 프레임에 묶으면 안 된다. `TraceDispatcher`는 ENCLOSING 전용으로 셀을 키로 하는 저장소를 따로 둔다.

- `_enclosing_var_ids` — 셀별 변수 ID
- `_enclosing_states` — 셀별 이전 상태
- `_enclosing_cell_refs` — 셀에 대한 강한 참조

셀 객체는 해시 불가능하므로 세 딕셔너리 모두 `id(cell)`을 키로 쓴다. `id()`는 객체가 죽으면 재사용되므로, 추적이 활성화된 동안 셀이 살아 있도록 `_enclosing_cell_refs`가 강한 참조를 붙잡는다. 이것이 없으면 셀이 GC된 뒤 같은 주소에 다른 객체가 들어와 이력이 뒤섞인다.

## 셀을 찾는 방법: 휴리스틱이라는 점

문제는 `sys.settrace` 콜백이 **프레임만 넘겨준다**는 것이다. 그리고 맨 프레임으로부터 클로저 셀 자체에 도달하는 공식 API가 없다.

실측으로 확인된 바로는 `frame.f_locals`, `gc.get_referents(frame)`, 안정 C-API인 `PyFrame_GetVar` 모두 **역참조된 값만** 반환하고 셀 객체는 주지 않는다. 셀은 함수 객체의 `__closure__`를 통해서만 접근 가능하다.

그래서 `_ClosureResolver`는 역방향으로 접근한다 — 호출자 프레임(`frame.f_back`)의 지역·전역 네임스페이스를 훑어, 다음 두 조건을 만족하는 콜러블을 찾는다.

1. 추적 중인 프레임과 **같은 코드 객체**를 사용한다
2. 해당 인덱스의 셀 내용이 추적 중인 프레임의 **현재 값과 동일 객체**다

2번이 필요한 이유는 앞서 말한 "같은 코드, 다른 셀" 상황 때문이다. 코드 객체만으로는 여러 클로저 인스턴스를 구별할 수 없다.

바운드 메서드도 다루기 위해 후보에서 `__func__`를 먼저 풀어낸다.

### 한계

이것은 보장이 아니라 휴리스틱이다. **호출 시점에 호출자의 네임스페이스에서 평범한 이름으로 접근 가능하지 않았던 콜러블**은 셀을 해석하지 못한다.

- `outer()()` 처럼 이름에 바인딩되지 않고 즉시 호출된 경우
- 속성 접근이나 딕셔너리 조회를 통해 호출된 콜백

이 경우 `resolve()`는 `None`을 반환하며, 호출하는 쪽은 이를 **"실패"가 아니라 "소유권을 판단할 수 없음"** 으로 해석해 그에 맞게 폴백해야 한다.

### 미해석 상태의 구분

`_frame_cell_cache`는 `_UNRESOLVED` 센티널을 사용한다. "이 프레임에 대해 아직 해석을 시도하지 않음"과 "시도했지만 휴리스틱이 찾지 못함(진짜 `None`)"을 구별하기 위해서다. 이 구분이 없으면 실패한 해석을 매 줄 재시도하게 된다.

## BUILTIN과 NOT_FOUND의 취급

두 도메인은 추적 대상이 아니다(`TRACKABLE_DOMAINS`는 LOCAL·GLOBAL·ENCLOSING뿐).

다만 판정 결과로서는 의미가 있다. 이전 상태가 있었는데 이 도메인으로 떨어졌다면 변수가 스코프에서 사라진 것이므로 `deleted`로 기록하고, 이전 상태도 없었다면 `not_found`로 처리한다.