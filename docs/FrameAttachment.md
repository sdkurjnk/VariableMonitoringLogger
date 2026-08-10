# 프레임 부착 전략

`TraceDispatcher`가 어떤 프레임에 라인 트레이싱을 걸지 결정하는 방식을 정리한다.

관련 코드: `TraceDispatcher._trace_calls`, `_ensure_frame_tracking`, `_ensure_active_ancestor_tracking`, `_make_line_tracer`, `register`

---

## 전역 훅을 "call" 이벤트로 좁힌 이유

`sys.settrace`에 등록된 `_trace_calls`는 `event != "call"`이면 즉시 `None`을 반환한다. 전역 훅의 역할을 **"이 새 프레임에 라인 트레이싱을 걸 것인가"**를 결정하는 것 하나로 한정한 것이다.

이는 비용 때문이다. 전역 훅에서 라인 이벤트까지 받으면 무관한 코드도 매 줄 파이썬 콜백을 거친다. 대신 `_relevant_for()`가 `_tracker_codes`와 `_tracker_globals`로부터  관련 여부를 판정하고, 관련 없는 프레임에는 로컬 트레이서를 아예 붙이지 않는다.

결과적으로 부착되지 않은 프레임에서는 이후 비용이 발생하지 않는다.

## 대가: 이미 실행 중이던 프레임

"call" 이벤트에만 반응한다는 것은 **훅 설치 시점에 이미 실행 중이던 프레임은 잡히지 않는다**는 뜻이다. 그 프레임들은 다시 "call"을 내지 않기 때문이다. 이는 `sys.settrace`의 성질이다.

그래서 `register()`는 **수동 부착 경로**를 갖는다. 등록 프레임의 "call"은 tracker가 생기기 전에 이미 발생했으므로, 그 프레임에 라인 트레이서를 직접 붙인다.

```python
frame_state = self._ensure_frame_tracking(frame) #TrcerDispathcer.py - line 260
```

`register()`에 넘어오는 `frame`은 `sys._getframe(1)`로 잡은 직접 호출자다.

## 두 가지 등록 경로

| 경로 | 대상 | 시점 |
|---|---|---|
| `_trace_calls` (자동) | register 이후 새로 생성되는 프레임 | "call" 이벤트 시 |
| `register()` (수동) | 모듈 범위 내 관련 프레임 | register 실행 중 |

추적 가능 기준은 스택상의 위치가 아니라 **`sys.settrace` 호출 시점 대비 프레임의 생성 시점**이다.

수동 부착은 등록 프레임에서 끝나지 않는다. 등록 프레임의 지역 변수를 shadowing 없이 참조할 수 있는 조상 프레임(같은 code 객체를 재귀 중인 프레임, 또는 같은 globals dict를 쓰는 프레임)에서 일어나는 변경도 잡아야 하므로, `register()`는 `_ensure_active_ancestor_tracking(frame, is_new_tracker)`으로 `frame.f_back`을 거슬러 올라가며 각 조상에 대해 `_relevant_for()`로 관련 여부를 판정하고, 관련 있는 프레임에만 라인 트레이서를 붙인다.

이 탐색은 무한정 올라가지 않는다. `co_name == "<module>"`인 프레임을 만나면 그 프레임까지는 처리하고 즉시 멈춘다. `<module>` 프레임은 이 실행 단위(대상 파일, 하나의 `exec()` 호출, 하나의 Jupyter 셀)의 최상단이기 때문이다. 여기서 멈추지 않으면, 같은 globals dict를 재사용하는 무관한 실행 단위(중첩 `exec()`, 노트북 셀 러너)나 이 코드를 호출한 인터프리터/테스트 러너 프레임까지 관련 있다고 잘못 판정해 추적을 붙이게 된다.

### 조상 탐색의 조기 종료

`is_new_tracker`가 `False`인 호출(기존 tracker를 재사용하는 dedup 등록)은 이 탐색 도중 이미 `_frame_states`에 있는 조상을 만나면 그 지점에서 즉시 멈춘다. 그 조상은 이전 등록에서 이미 라인 트레이서가 붙었고, relevance는 캐싱되지 않고 매 line/return 이벤트마다 `_relevant_for()`로 새로 계산되므로, 프레임이 한 번 추적되기 시작하면 그 이후 어떤 tracker가 추가되든 다음 라인에서 자동으로 반영된다. 즉 그 위 체인은 이전 등록에서 이미 처리가 끝난 상태임이 보장된다.

반대로 새 tracker가 생성되는 호출(`is_new_tracker=True`)은 이 조기 종료를 적용하지 않고 `<module>`까지 전체를 훑는다. 새 tracker의 등장은 `_frame_cache`를 무효화해 어떤 code 객체에 어떤 tracker가 관련 있는지 자체를 바꿀 수 있으므로, 이미 추적 중인 조상이라 해도 다시 판정해야 하기 때문이다.

같은 code 객체가 재귀 매 depth마다 같은 변수를 등록하는 패턴(각 프레임이 직전 프레임을 이미 추적 중인 상태로 만나는 경우)에서, 이 조기 종료가 없으면 매 등록마다 조상 체인 전체를 다시 훑어 총비용이 재귀 깊이의 제곱에 가깝게 증가한다.

## 라인 트레이서를 프레임마다 새로 만드는 이유

`_ensure_frame_tracking`은 `_make_line_tracer(frame_state)`로 만든 **프레임 전용 클로저**를 `f_trace`에 붙인다. 각 트레이서가 자기 프레임 전용 `frame_state`를 캡처해야 하기 때문이다. 같은 코드 객체가 여러 프레임에서 동시에 살아 있는 상황(재귀)에서 각 호출이 독립된 변수 상태를 갖도록 보장한다. 

만약 코드 객체를 키로 상태를 공유했다면 재귀 호출들이 서로의 이전 값을 덮어썼을 것이다.

## 정리 시점

로컬 트레이서는 매번 자기 자신을 반환해 다음 라인에서도 호출되고, `return` 이벤트에서 `None`을 반환해 스스로를 떼어낸다.

이때 `_frame_states`와 `_frame_cell_cache`에서 해당 프레임 항목을 제거한다. 프레임을 키로 쓰는 자료구조이므로, 이 정리가 빠지면 상태가 프레임보다 오래 살아남아 누수가 된다.

## 제너레이터와 코루틴

suspend된 제너레이터 프레임은 스택에 없어 `f_back` 체인에 존재하지 않는다. 다만 CPython은 resume될 때마다 "call" 이벤트를 다시 내므로 자동 경로로 처리된다. 부작용으로 resume마다 호출 컨텍스트가 재생성된다(→ [호출 컨텍스트 트리](./CallContext.md)).
