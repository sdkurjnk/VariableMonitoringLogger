# 상태 자료구조와 상호작용

`TraceDispatcher`가 들고 있는 딕셔너리들이 각각 무엇을 책임지고, 어떻게 맞물려 도는지 정리한다.

관련 코드: `TraceDispatcher.__init__`, `register`, `_get_cache_entry`, `_relevant_for`, `_check_and_log`, `unregister`, `_stop_tracing`

---

## 세 개의 층

딕셔너리가 많아 보이지만 역할은 세 층으로 나뉜다.

| 층 | 자료구조 | 질문 |
|---|---|---|
| **등록** | `_registered_local`, `_registered_global` | 이 변수는 이미 등록되어 있는가? |
| **선별** | `_frame_cache`, `_tracker_codes`, `_tracker_globals` | 이 프레임을 추적해야 하는가? |
| **상태** | `_frame_states`, `_global_states` | 이 변수의 직전 값은 무엇이었는가? |

각 층은 서로 다른 수명을 갖는다. 등록 정보는 tracker와 함께 살고, 선별 캐시는 tracker 목록이 바뀔 때 무효화되며, 상태는 소유자(프레임 또는 tracker)를 따라간다.

---

## 등록 층: 중복 제거

`register()`가 같은 변수에 대해 여러 번 호출되는 것은 정상이다. 재귀 함수나 반복문 안에 있으면 호출마다 실행된다. 매번 새 tracker를 만들면 `_trackers`가 무한히 자라고, 같은 변수의 이력이 여러 갈래로 쪼개진다.

두 딕셔너리가 중복 제거 키 역할을 한다.

```python
if is_local:
    dedup_key = (varName, frame.f_code)          # → _registered_local
else:
    dedup_key = (varName, id(frame.f_globals))   # → _registered_global
```

키 구성이 다른 이유는 **동일성의 기준이 다르기** 때문이다.

- LOCAL은 코드 객체 단위다. 같은 함수의 서로 다른 호출은 같은 tracker를 공유해야 한다
- GLOBAL은 모듈 단위다. 어느 함수에서 등록하든 같은 모듈의 같은 전역 변수면 하나의 tracker다

키가 이미 있으면 기존 tracker를 그대로 재사용하고, tracker 생성 과정 전체를 건너뛴다.

---

## 선별 층: 2단계 필터

프레임 관련성 판정은 **싼 검사로 후보를 좁히고, 정확한 검사로 확정하는** 2단계 구조다. 매 "call" 이벤트마다 도는 경로라 비용이 중요하다.

### 1단계 — `_frame_cache` (코드 객체 단위 캐시)

```python
names = set(code.co_varnames) | set(code.co_cellvars) | set(code.co_freevars)
local_candidates  = [t for t in self._trackers if t.varName in names]
global_candidates = [t for t in self._trackers if t.varName not in names]
entry = (local_candidates, global_candidates, frame.f_globals)
self._frame_cache[code] = entry
```

전체 tracker 목록을 훑어 **이름이 이 코드 객체의 지역 이름 집합에 속하는지**로 후보를 가른다. 코드 객체의 정적 정보만 쓰므로 같은 함수의 모든 프레임에서 결과가 동일하고, 따라서 `f_code`를 키로 캐싱할 수 있다.

이 캐싱이 없으면 함수 호출마다 tracker 목록 전체를 선형 탐색하게 된다.

엔트리에 `frame.f_globals`를 함께 저장하는데, 이는 캐시를 채운 첫 프레임의 globals다. 같은 코드 객체가 다른 globals에서 실행되는 경우(`exec`에 별도 네임스페이스를 넘기는 등)를 감지하는 가드로 쓰인다.

### 2단계 — `_tracker_codes` / `_tracker_globals` (identity 확정)

1단계는 **이름만** 본다. 다른 모듈의 동명 함수, 동명 전역 변수가 그대로 통과한다. 2단계가 등록 시점의 실제 스코프와 대조해 확정한다.

```python
local_relevant = [t for t in local_candidates
                  if self._tracker_codes.get(t) is frame.f_code]

global_relevant = []
if global_candidates and frame.f_globals is entry_globals:
    global_relevant = [t for t in global_candidates
                       if self._tracker_globals.get(t) is frame.f_globals]
```

`is` 비교인 점이 중요하다. 이름이 아니라 **객체 동일성**이므로, 같은 이름의 다른 함수·다른 모듈이 섞이지 않는다.

### 이 정보를 tracker가 아니라 dispatcher가 들고 있는 이유

`_tracker_codes[tracker] = frame.f_code` 형태로 dispatcher 쪽 딕셔너리에 저장한다. tracker 객체의 속성으로 두지 않는 이유는, tracker가 **등록 시점의 스코프에만** 적용되도록 못 박기 위해서다. tracker에 붙여두면 이후 다른 프레임에서 재사용될 때 스코프 정보가 함께 따라다니며 오염될 여지가 생긴다.

부수적으로 `unregister()`에서 중복 제거 키를 역산하는 데도 쓰인다.

```python
code = self._tracker_codes.pop(tracker, None)
if code is not None:
    self._registered_local.pop((tracker.varName, code), None)
```

### 캐시 무효화

`_frame_cache`는 `_trackers`에서 파생된 캐시다. tracker 목록이 바뀌면 후보 분류가 달라지므로 반드시 버려야 한다.

```python
self._frame_cache.clear()   # register()에서 새 tracker 생성 시
self._frame_cache.clear()   # unregister()에서
```

중복 제거로 기존 tracker를 재사용한 경우에는 목록이 바뀌지 않으므로 무효화하지 않는다.

---

## 상태 층: 저장소 간접화

`_check_and_log`는 저장소와 키를 **인자로 받는다.**

```python
def _check_and_log(self, frame, tracker, storage, key, domain, cell=None):
    prev_state = storage.get(key)
    ...
    storage[key] = new_state
```

호출부가 도메인에 따라 다른 조합을 넘긴다.

| 도메인 | storage | key | 근거 |
|---|---|---|---|
| LOCAL | `frame_state` | `varName` | 값이 프레임마다 독립적이다 |
| GLOBAL | `self._global_states` | `tracker` | 모든 프레임이 하나의 타임라인을 공유한다 |
| ENCLOSING | `self._enclosing_states` | `id(cell)` | 값의 소유자가 셀이다 |

같은 판정 로직을 쓰면서 **상태의 소유자만 갈아끼우는** 구조다. 도메인별로 분기된 세 벌의 판정 코드를 만들지 않아도 된다.

### 왜 GLOBAL은 프레임 상태에 둘 수 없나

전역 변수는 어느 프레임에서 바뀌든 하나의 변수다. 프레임별로 이전 값을 들고 있으면, `foo`에서 바꾼 값이 `bar`의 기준값에 반영되지 않아 같은 변경이 중복 기록되거나 놓친다.

같은 이유로 `_global_var_ids`가 별도로 존재한다. 전역 변수는 이후 어느 프레임에서 변경되더라도 **처음 등록된 프레임의 ID**를 계속 유지해야, 이력을 한 변수의 것으로 이어 읽을 수 있다.

---

## 흐름 1: `register()`

```
resolve() → 도메인 판정
     ↓
_registered_local / _registered_global 조회
     ↓
  [있음] 기존 tracker 재사용 ─────────────┐
     ↓                                    │
  [없음] VariableTracker 생성             │
         _trackers 에 추가                │
         _registered_* 에 키 등록          │
         _tracker_codes / _tracker_globals │
           에 스코프 identity 기록          │
         _frame_cache.clear()             │
     ↓                                    │
     └────────────────────────────────────┘
     ↓
_start_tracing()  → sys.settrace(_trace_calls)
     ↓
_ensure_frame_tracking(frame)  → _frame_states 에 항목 생성 + f_trace 부착
     ↓
_check_and_log(...)  → 초기값 기록 (init 이벤트)
```

## 흐름 2: 실행 중인 한 줄

```
line 이벤트 → trace_lines(클로저, frame_state 캡처)
     ↓
_process_frame(frame, frame_state)
     ↓
_relevant_for(frame)
     ├─ _get_cache_entry(frame)      → _frame_cache 조회/생성
     └─ _tracker_codes / _tracker_globals 로 확정
     ↓
local_relevant  → _check_and_log(frame_state, varName)
global_relevant → _check_and_log(_global_states, tracker)
     ↓
변경됨 → HistoryBuffer.append()
```

## 흐름 3: 정리

**프레임 반환 시** — `_frame_states`와 `_frame_cell_cache`에서 해당 프레임 항목만 제거. 프레임 객체를 키로 쓰므로, 이 정리가 빠지면 상태가 프레임보다 오래 살아남아 누수가 된다.

**`unregister(tracker)`** — 그 tracker가 소유한 것만 정확히 걷어낸다. `_tracker_codes` / `_tracker_globals`에서 등록 시점 스코프를 꺼내 중복 제거 키를 역산하고, `_tracker_cells`에 기록해둔 셀 목록으로 ENCLOSING 저장소를 정리한다. 셀 목록을 따로 두는 이유는, 이것 없이는 어느 셀이 어느 tracker의 것인지 알 수 없어 다른 tracker의 상태까지 지우거나 남기게 되기 때문이다.

**`_stop_tracing()`** — 위 딕셔너리 전부를 `clear()` 한다. `sys.settrace(None)` 이후에는 어떤 상태도 유효하지 않으므로 남길 이유가 없다.

---

## 수명 요약

| 자료구조 | 키 | 제거 시점 |
|---|---|---|
| `_registered_local` | `(varName, f_code)` | `unregister` / `stop` |
| `_registered_global` | `(varName, id(f_globals))` | `unregister` / `stop` |
| `_tracker_codes` | tracker | `unregister` / `stop` |
| `_tracker_globals` | tracker | `unregister` / `stop` |
| `_frame_cache` | `f_code` | tracker 목록 변경 시 전체 무효화 |
| `_global_states` | tracker | `unregister` / `stop` |
| `_global_var_ids` | tracker | `unregister` / `stop` |
| `_frame_states` | frame | 해당 프레임 `return` / `stop` |
| `_frame_cell_cache` | frame | 해당 프레임 `return` / `stop` |
| `_enclosing_states` | `id(cell)` | `unregister` / `stop` |

프레임을 키로 쓰는 두 개만 프레임 수명을 따르고, 나머지는 tracker 수명을 따른다. ENCLOSING 저장소가 프레임이 아니라 셀에 묶인 이유는 [스코프 해석](./scope-resolution.md) 문서를 참고할 것.