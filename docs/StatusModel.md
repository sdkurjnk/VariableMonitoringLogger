# 상태 자료구조와 상호작용

`TraceDispatcher`가 들고 있는 딕셔너리들이 무엇을 책임지고 어떻게 맞물리는지 정리한다.

관련 코드: `TraceDispatcher.__init__`, `register`, `_get_cache_entry`, `_relevant_for`, `_check_and_log`, `unregister`, `_stop_tracing`

---

## 세 개의 층

| 층 | 자료구조 | 질문 |
|---|---|---|
| **등록** | `_registered_local`, `_registered_global` | 이 변수는 이미 등록되어 있는가? |
| **선별** | `_frame_cache`, `_tracker_codes`, `_tracker_globals` | 이 프레임을 추적해야 하는가? |
| **상태** | `_frame_states`, `_global_states` | 이 변수의 직전 값은 무엇이었는가? |

수명이 서로 다르다 — 등록 정보는 tracker와 함께 살고, 선별 캐시는 tracker 목록이 바뀔 때 무효화되며, 상태는 소유자(프레임 또는 tracker)를 따라간다.

---

## 등록 층: 중복 제거

`register()`는 같은 변수에 여러 번 호출되는 게 정상이다(재귀·반복문). 매번 새 tracker를 만들면 `_trackers`가 무한히 자라고 이력이 갈라진다. 두 딕셔너리가 중복 제거 키 역할을 한다.

```python
if is_local:
    dedup_key = (varName, frame.f_code)          # → _registered_local
else:
    dedup_key = (varName, id(frame.f_globals))   # → _registered_global
```

키 구성이 다른 이유는 동일성 기준이 다르기 때문이다 — LOCAL은 코드 객체 단위(같은 함수의 다른 호출은 tracker 공유), GLOBAL은 모듈 단위(어느 함수에서 등록하든 같은 모듈의 같은 전역이면 하나). 키가 이미 있으면 기존 tracker를 재사용하고 생성을 건너뛴다.

---

## 선별 층: 2단계 필터

매 "call"마다 도는 경로라, **싼 검사로 후보를 좁히고 정확한 검사로 확정한다.**

### 1단계 — `_frame_cache` (코드 객체 단위 캐시)

```python
names = set(code.co_varnames) | set(code.co_cellvars) | set(code.co_freevars)
local_candidates  = [t for t in self._trackers if t.varName in names]
global_candidates = [t for t in self._trackers if t.varName not in names]
entry = (local_candidates, global_candidates)
```

**이름이 이 코드 객체의 지역 이름 집합에 속하는지**로 후보를 가른다. 이 분류는 코드 객체의 정적 정보만 사용하므로 같은 코드 객체의 모든 프레임에서 결과가 같고, `f_code`를 키로 안전하게 캐싱할 수 있다. 캐시에는 프레임마다 달라질 수 있는 `f_globals`를 저장하지 않는다. 실제 GLOBAL 스코프의 동일성은 2단계에서 현재 프레임을 기준으로 판정한다.

### 2단계 — `_tracker_codes` / `_tracker_globals` (identity 확정)

1단계는 **이름만** 본다. 다른 모듈의 동명 함수·동명 전역이 통과한다. 2단계가 등록 시점의 실제 스코프와 `is`로 대조해 확정한다.

```python
local_relevant = [t for t in local_candidates
                  if self._tracker_codes.get(t) is frame.f_code]

global_relevant = [t for t in global_candidates
                   if self._tracker_globals.get(t) is frame.f_globals]
```

이름이 아니라 **객체 동일성**을 검사하므로 동명 함수·모듈이 섞이지 않는다. 같은 코드 객체가 서로 다른 `globals`에서 실행되더라도 후보 캐시는 공유할 수 있지만, GLOBAL tracker는 현재 `frame.f_globals`와 등록 당시의 globals가 동일한 경우에만 선택된다.

이 정보를 tracker가 아니라 dispatcher가 드는 이유는, tracker가 **등록 시점 스코프에만** 적용되도록 못 박기 위해서다. tracker에 붙이면 다른 프레임에서 재사용될 때 스코프 정보가 따라다니며 오염된다. 부수적으로 `unregister()`에서 중복 제거 키를 역산하는 데도 쓴다.

`_frame_cache`는 `_trackers`에서 파생된 캐시이므로 목록이 바뀌면(`register`의 새 tracker 생성, `unregister`) `clear()` 한다. 중복 제거로 재사용한 경우는 목록이 그대로라 무효화하지 않는다.

---

## 상태 층: 저장소 간접화

`_check_and_log`는 저장소와 키를 **인자로 받는다.**

```python
def _check_and_log(self, frame, tracker, storage, key, domain, cell=None):
    prev_state = storage.get(key)
    ...
    storage[key] = new_state
```

| 도메인 | storage | key | 근거 |
|---|---|---|---|
| LOCAL | `frame_state` | `varName` | 값이 프레임마다 독립 |
| GLOBAL | `self._global_states` | `tracker` | 모든 프레임이 하나의 타임라인 공유 |
| ENCLOSING | `self._enclosing_states` | `id(cell)` | 값의 소유자가 셀 |

같은 판정 로직을 쓰며 **상태 소유자만 갈아끼우는** 구조라, 도메인별 판정 코드를 세 벌 만들 필요가 없다.

**GLOBAL을 프레임 상태에 둘 수 없는 이유** — 전역은 어느 프레임에서 바꾸든 하나의 변수다. 프레임별로 이전 값을 들면 `foo`에서 바꾼 값이 `bar`의 기준값에 반영되지 않아 중복 기록되거나 놓친다. 같은 이유로 `_global_var_ids`는 이후 어느 프레임에서 변경돼도 **처음 등록된 프레임의 ID**를 유지해, 이력을 한 변수의 것으로 이어 읽게 한다.

---

## 흐름

**`register()`**
```
resolve() → 도메인 판정
  → _registered_* 조회
      [있음] 기존 tracker 재사용
      [없음] VariableTracker 생성 → _trackers 추가
             → _registered_* / _tracker_codes / _tracker_globals 기록
             → _frame_cache.clear()
  → _start_tracing()  → sys.settrace(_trace_calls)
  → _ensure_frame_tracking(frame)  → _frame_states 항목 생성 + f_trace 부착
  → _check_and_log(...)  → 초기값 기록 (init)
```

**실행 중인 한 줄**
```
line 이벤트 → trace_lines(frame_state 캡처)
  → _process_frame(frame, frame_state)
  → _relevant_for(frame)   [_get_cache_entry + _tracker_codes/_globals 확정]
  → local  → _check_and_log(frame_state, varName)
    global → _check_and_log(_global_states, tracker)
  → 변경됨 → HistoryBuffer.append()
```

**정리**
- **프레임 실제 종료** — suspend가 아닌 실제 종료에서 `_frame_states`·`_frame_cell_cache`의 해당 프레임만 제거한다. 제너레이터와 코루틴의 suspend에서는 resume 이후 같은 비교 기준을 사용해야 하므로 상태를 유지한다.
- **`unregister(tracker)`** — 그 tracker가 소유한 것만 걷어낸다. `_tracker_codes`/`_tracker_globals`에서 스코프를 꺼내 중복 제거 키를 역산하고, `_tracker_cells`의 셀 목록으로 ENCLOSING 저장소를 정리한다. 셀 목록이 없으면 어느 셀이 어느 tracker 것인지 알 수 없어 남의 상태까지 지운다.
- **`_stop_tracing()`** — `sys.settrace(None)` 이후엔 어떤 상태도 무효하므로 전부 `clear()`.

---

## 수명 요약

| 자료구조 | 키 | 제거 시점 |
|---|---|---|
| `_registered_local` | `(varName, f_code)` | `unregister` / `stop` |
| `_registered_global` | `(varName, id(f_globals))` | `unregister` / `stop` |
| `_tracker_codes` | tracker | `unregister` / `stop` |
| `_tracker_globals` | tracker | `unregister` / `stop` |
| `_tracker_cells` | tracker | `unregister` / `stop` |
| `_frame_cache` | `f_code` | tracker 목록 변경 시 전체 무효화 |
| `_global_states` | tracker | `unregister` / `stop` |
| `_global_var_ids` | tracker | `unregister` / `stop` |
| `_enclosing_states` | `id(cell)` | `unregister` / `stop` |
| `_enclosing_var_ids` | `id(cell)` | `unregister` / `stop` |
| `_enclosing_cell_refs` | `id(cell)` | `unregister` / `stop` |
| `_frame_states` | frame | 해당 프레임의 실제 종료 / `stop` |
| `_frame_cell_cache` | frame | 해당 프레임의 실제 종료 / `stop` |

프레임을 키로 쓰는 둘만 프레임 수명을 따르고 나머지는 tracker 수명을 따른다. ENCLOSING 저장소가 프레임이 아니라 셀에 묶인 이유는 [스코프 해석](./ScopeResolution.md)을 참고.
