# oscilo

Python 변수 변화를 코드 수정 없이 자동으로 추적하는 라이브러리. 변수 이름을 한 번만 등록하면 `oscilo`가 그 변수의 모든 변화를 기록합니다.

[![PyPI version](https://img.shields.io/pypi/v/oscilo)](https://pypi.org/project/oscilo/)
[![Python](https://img.shields.io/pypi/pyversions/oscilo)](https://pypi.org/project/oscilo/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

[English](./README.md) | **한국어**

`oscilo`는 프로그램 실행을 백그라운드에서 관찰하여 변수가 시간에 따라 어떻게 변하는지(재할당, 인플레이스 변경, 삭제)를 포착하고, 프로그램이 종료되는 시점에 전체 이력을 JSON Lines 파일로 기록합니다. 매 줄마다 수행되는 값 비교는 작은 C 확장 모듈에 위임하여 런타임 오버헤드를 낮게 유지합니다.

## 목차

- [배경](#배경)
- [설치](#설치)
- [빠른 시작](#빠른-시작)
- [출력 형식](#출력-형식)
- [동작 원리](#동작-원리)
- [프로젝트 구조](#프로젝트-구조)
- [테스트](#테스트)
- [기여](#기여)
- [라이선스](#라이선스)

## 배경

디버깅 중 변수 상태를 확인하려면 보통 코드 곳곳에 `print`를 흩뿌리게 됩니다.

```python
def solve(data):
    result = []
    for x in data:
        result.append(x * 2)
        print("result:", result)   # 임시 코드, 제거를 잊기 쉬움
    return result
```

이 방식은 소스를 지저분하게 만들고, 지우지 않은 채 남기 쉬우며, 반복이 많은 코드에는 적합하지 않습니다. 대화형 디버거는 코드 오염은 피할 수 있지만 실행을 멈추기 때문에, 루프가 수천 번 도는 경우에는 비실용적입니다.

`oscilo`는 다른 접근을 택합니다. 변수 이름을 한 번만 등록하면 이력이 자동으로 수집됩니다.

```python
import oscilo

def solve(data):
    result = []
    oscilo.register("result")   # 이 시점 이후 result의 모든 변화가 기록됨
    for x in data:
        result.append(x * 2)
    return result
```

## 설치

```bash
pip install oscilo
```

`oscilo`는 C 확장 모듈을 포함합니다. 미리 빌드된 wheel이 있으면 그대로 사용되고, 없으면 로컬에서 컴파일되며 이 경우 C 컴파일러가 필요합니다.

<details>
<summary>소스에서 빌드하기</summary>

```bash
pip install -e .                        # 편집 가능 모드 설치 (개발 시 권장)
pip install .                           # 일반 설치
python setup.py build_ext --inplace     # C 확장만 빌드
```
</details>

**요구 사항**

- Python 3.11 이상
- 소스 빌드 시 C 컴파일러 (GCC / Clang / MSVC)

## 빠른 시작

공개 API는 `oscilo.register()` 함수 하나이며, 변수 이름을 문자열로 받습니다.

```python
import oscilo

def run():
    target = [100, 200]
    oscilo.register("target")   # "init" 이벤트로 기록됨

    target.append(300)          # updated (인플레이스 변경)
    target = "reassigned"       # updated (재할당)
    del target                  # deleted (삭제)

run()
# 종료 시 이력이 ocilo.jsonl에 기록됨
```

`oscilo.register()`를 여러 번 호출하면 각 변수가 동일한 모니터에 추가되며, 모든 이력은 하나의 출력 파일로 병합됩니다.

```python
import oscilo

def run():
    score = 10
    items = ["potion", "shield"]

    oscilo.register("score")
    oscilo.register("items")

    score += 55
    items.append("sword")

run()
```

참고:

- `register()`는 `None`을 반환합니다. 등록이 유일한 효과입니다.
- `oscilo`를 import하는 것만으로는 아무 부작용이 없습니다. `register()`를 호출해야 추적이 시작됩니다.
- 변화가 한 번도 기록되지 않으면 파일을 생성하지 않습니다.

## 출력 형식

이력은 [JSON Lines](https://jsonlines.org/) 형식으로 기록됩니다(기본 파일명 `ocilo.jsonl`). 각 줄이 하나의 변화를 나타냅니다.

```json
{"name": "target", "data": [100, 200], "event": "init", "domain": "LOCAL", "line": 4}
{"name": "target", "data": [100, 200, 300], "event": "updated", "domain": "LOCAL", "line": 6}
{"name": "target", "data": "reassigned", "event": "updated", "domain": "LOCAL", "line": 7}
{"name": "target", "data": null, "event": "deleted", "domain": "LOCAL", "line": 8}
```

| 필드 | 설명 |
|------|------|
| `name` | 추적 중인 변수 이름 |
| `data` | 변화 시점의 값 (`deleted`일 때는 `null`) |
| `event` | `init`, `updated`, `deleted` |
| `domain` | 변수 스코프: `LOCAL`, `GLOBAL`, `UNKNOWN` |
| `line` | 변화가 감지된 소스 코드 줄 번호 |

줄 단위 형식이라 이력이 커도 스트리밍과 파싱이 효율적입니다.

## 동작 원리

`oscilo`는 Python에서 실행을 관찰하고, 값 비교는 C 확장 모듈에 위임합니다.

1. 첫 `register()` 호출 시 단일 모니터가 지연 생성되고 `sys.settrace`로 트레이스 훅이 설치됩니다.
2. 코드가 한 줄 실행될 때마다, C 엔진(`oscilo_engine`)이 추적 대상 변수의 변화 여부를 아래 단락 평가(short-circuit) 순서로 판단합니다.

   ```
   변수가 스코프에서 사라졌는가?        → deleted
   참조 주소가 바뀌었는가?             → updated   (재할당)
   불변 타입인가? (int/str/...)        → 변화 없음 (비교 생략)
   컨테이너 크기가 달라졌는가?          → updated
   그 외에는 값을 비교                 → updated / 변화 없음
   ```

3. 프로세스가 종료되면 `atexit` 훅이 메모리에 모은 이력을 한 번의 쓰기로 디스크에 플러시합니다. 변화마다 기록하지 않고 버퍼에 모으는 것은 I/O 오버헤드를 피하기 위함입니다.

값이 바뀌지 않으면 아무것도 기록하지 않고, 불변 값은 참조가 그대로면 비교 자체를 건너뜁니다. 두 가지 모두 줄당 비용을 낮게 유지하는 핵심입니다.

## 프로젝트 구조

```
src/oscilo/
├── __init__.py          # 공개 API(register)와 단일 인스턴스 관리
├── _core.py             # 모니터 구현 및 atexit 저장 로직
├── FileWriter.py        # JSONL 출력
├── HistoryBuffer.py     # 메모리 내 이력 버퍼
├── ScopeResolver.py     # 지역/전역 스코프 해석
├── TraceDispatcher.py   # sys.settrace 이벤트 처리
├── VariableTracker.py   # 변수별 상태 및 스냅샷
└── oscilo_engine.c      # 값 비교를 담당하는 C 확장 모듈
```

## 테스트

```bash
python tests/test.py
```

`tests/`에서 `test_*.py`를 자동으로 찾아 실행합니다. 각 시나리오는 별도 인터프리터 프로세스로 실행되는데, `atexit` 기반 저장과 `sys.settrace` 동작은 전체 프로세스 생명주기에 걸쳐야만 검증할 수 있기 때문입니다.

## 기여

버그 제보, 기능 아이디어, 풀 리퀘스트 모두 환영합니다.

- 버그 리포트 또는 기능 제안 템플릿으로 이슈를 열어주세요.
- PR을 보낼 때는 `.github/pull_request_template.md`의 체크리스트를 따라주세요.
- 새 기능이나 수정에는 가능하면 테스트를 함께 포함해주세요.

## 라이선스

[MIT](./LICENSE) © 2026 [sdkurjnk](https://github.com/sdkurjnk)
