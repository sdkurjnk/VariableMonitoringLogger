# 스코프 해석

변수 이름 하나가 어느 스코프에 속하는지 판정하는 방식과, ENCLOSING을 다루기 위한 타협을 정리한다.

관련 코드: `ScopeResolver.resolve`, `ScopeResolver.resolve_cell`

---

## LEGB 판정 순서

`ScopeResolver.resolve()`는 **런타임 딕셔너리가 아니라 코드 객체의 정적 정보**를 먼저 본다.

```
co_varnames / co_cellvars 에 있음  → LOCAL
co_freevars 에 있음                → ENCLOSING
f_globals 에 있음                  → GLOBAL
f_builtins 에 있음                 → BUILTIN
그 외                              → NOT_FOUND
```

`co_cellvars`가 LOCAL인 이유는, 내부 함수에 캡처되는 변수라도 **선언된 프레임 입장에서는 지역 변수**이기 때문이다. 그 변수를 자유 변수로 참조하는 내부 함수에서만 ENCLOSING이 된다.

## 선언된 지역 변수는 미바인딩 상태에서도 외부를 가리지 않는다

가장 중요한 규칙이다. 이름이 `co_varnames`에 있는데 `f_locals`에 아직 없으면, 상위 스코프로 내려가지 않고 `NOT_FOUND`를 반환한다.

```python
if var_name in code.co_varnames or var_name in code.co_cellvars:
    if var_name in frame.f_locals:
        return LOCAL, frame.f_locals.get(var_name)
    return NOT_FOUND, None
```

파이썬 동작 그대로다 — 함수 안에 대입문이 하나라도 있으면 그 이름은 함수 전체에서 지역 변수이며, 할당 전 접근은 전역 값이 아니라 `UnboundLocalError`다. 여기서 상위로 폴백하면 **동명의 전역 값을 지역 변수의 값처럼 기록하는** 오류가 난다. 값이 없는 구간은 정직하게 `NOT_FOUND`로 남긴다.

## ENCLOSING의 소유권 문제

ENCLOSING은 **값의 소유자가 프레임이 아니라 클로저 셀**이라는 점에서 다르다.

```python
def outer():
    n = 0
    def inner():
        nonlocal n
        n += 1
    return inner
```

`inner` 프레임은 매 호출마다 새로 생기지만 `n`은 셀에 남아 이어진다. `outer()`를 두 번 호출하면 같은 코드 객체를 공유하는 **서로 다른 셀 두 개**가 생긴다. 따라서 identity와 이력을 프레임에 묶으면 안 되고, 셀(`id(cell)`)을 키로 삼는다.

- `VariableTracker._states[id(cell)]` — 셀별 이전 상태(비교 기준)
- `_enclosing_var_ids` — 셀별 변수 ID (dispatcher)
- `_enclosing_cell_refs` — 셀에 대한 강한 참조 (dispatcher)

셀은 해시 불가능하므로 모두 `id(cell)`을 키로 쓴다. `id()`는 객체가 죽으면 재사용되므로, `_enclosing_cell_refs`가 강한 참조로 셀을 붙잡아 GC 후 같은 주소에 다른 객체가 들어와 이력이 뒤섞이는 것을 막는다.

## 셀을 찾는 방법: 휴리스틱이라는 점

`sys.settrace` 콜백은 **프레임만 넘겨준다.** 실측상 `frame.f_locals`, `gc.get_referents(frame)`, `PyFrame_GetVar` 모두 **역참조된 값만** 주고 셀 객체는 주지 않는다 — 셀은 함수 객체의 `__closure__`로만 접근된다.

그래서 `ScopeResolver.resolve_cell`은 역방향으로, 호출자 프레임(`frame.f_back`)의 네임스페이스를 훑어 다음을 만족하는 콜러블을 찾는다.

1. 추적 중인 프레임과 **같은 코드 객체**를 쓴다
2. 해당 인덱스의 셀 내용이 추적 중인 프레임의 **현재 값과 동일 객체**다

2번이 필요한 이유는 "같은 코드, 다른 셀" 때문이다. 바운드 메서드를 위해 후보에서 `__func__`를 먼저 풀어낸다.

### 한계

보장이 아니라 휴리스틱이다. **호출 시점에 호출자 네임스페이스에서 평범한 이름으로 접근 가능하지 않았던 콜러블**은 셀을 해석하지 못한다.

- `outer()()`처럼 이름에 바인딩되지 않고 즉시 호출된 경우
- 속성 접근·딕셔너리 조회로 호출된 콜백

이때 `resolve()`는 `None`을 반환하며, 호출자는 이를 **"실패"가 아니라 "소유권 판단 불가"**로 해석해 폴백해야 한다.

`_frame_cell_cache`는 `_UNRESOLVED` 센티널로 "아직 시도 안 함"과 "시도했지만 못 찾음(진짜 `None`)"을 구별한다. 이 구분이 없으면 실패한 해석을 매 줄 재시도한다.

## BUILTIN과 NOT_FOUND

둘 다 추적 대상이 아니다(`TRACKABLE_DOMAINS`는 LOCAL·GLOBAL·ENCLOSING뿐). 다만 판정 결과로는 의미가 있다 — 이전 상태가 있었는데 이 도메인으로 떨어졌다면 `deleted`, 이전 상태도 없었다면 `not_found`로 처리한다.
