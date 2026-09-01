# 기여 가이드 — GitFlow 워크플로

oscilo는 GitFlow 기반의 자동화 릴리스 파이프라인을 쓴다. 기여자가 실제로 신경 쓸 일은
**`feature/* → develop` PR 하나를 잘 올리는 것**뿐이고, 태그·배포·`master` 병합은 전부 자동으로 처리된다.
이 문서는 그 하나를 어떻게 올리는지를 설명한다.

---

## 한눈에 보기

```text
 feature/*        develop                             master
    │                │                                  │
    ● PR: Label(major/minor/patch) + Review·CI          |    # 사람이 보는 유일한 PR
    │                │                                  │
    └───────────────>●                                  │
                     │           release/vX.Y.Z         │
              [auto] ●────────────────>●                |
                     |                 |                │
                     │                 |                │
          Actions-"Run workflow" (Finish release)       |
                     │                 ● [auto] tag vX.Y.Z
                     │                 │                │
                     ●<─[auto-merge]───┼──[auto-merge]─>●
             back-merge                │                │
                     |                 │                │     
                     │                 │   [auto] 병합 후 GitHub Release → PyPI
                     │                 X                |   #[auto] 브랜치 삭제 
                     |                                  |
                     ▼                                  ▼

 hotfix (출시 후 긴급): master ─[Actions "Make Hotfix"]▶ hotfix/vX.Y.(Z+1) ─수정▶
   〔사람 finalize〕▶ tag(Z+1) ▶ master·develop auto-merge ▶ Release→PyPI ▶ 삭제
```

당신은 `develop`으로 PR을 올리고 병합되게 만들면 끝이다. 그 뒤는 파이프라인이 알아서 한다.

---

## 1. 브랜치 이름 정하기

변경 종류에 따라 브랜치 접두사를 고른다. **접두사가 파이프라인 동작을 결정한다.**

| 접두사 | 언제 | 버전 라벨 | 병합 시 |
|--------|------|:--------:|---------|
| `feature/<이름>` | 기능 추가·버그 수정 등 **릴리스할 코드 변경** | **필요** | release 브랜치 생성(=배포 후보) |
| `docs/<이름>` | 문서만 변경 | 불필요 | release 안 만듦. 다음 release에 함께 실림 |
| `chore/<이름>` | 빌드·CI·잡무 등 비기능 변경 | 불필요 | release 안 만듦 |

- 기준 브랜치(base)는 **항상 `develop`** 이다. `master`로 직접 PR을 올리지 않는다(핫픽스만 예외 — §5).

- "릴리스에 버전을 매길 만한 변경인가?"가 `feature/*` 인지 아닌지의 기준이다. 애매하면 `feature/*`.

- **위 세 접두사 중 하나를 반드시 쓴다.** `feat/`·`fix/`처럼 다른 이름으로 올리면 파이프라인이 비버전 변경으로 취급해 라벨 검사도, release 생성도 없이 조용히 develop에 병합된다(버전이 오르지 않는다).

---

## 2. PR 올리기

### 2-1. `feature/*` PR — 버전 라벨을 정확히 하나
`feature/*` PR에는 `major` / `minor` / `patch` 중 **정확히 하나**를 붙인다. 이 라벨이 이번 변경의
다음 버전을 결정한다([유의적 버전](https://semver.org/lang/ko/)).

| 라벨 | 올리는 자리 | 언제 |
|------|------------|------|
| `major` | `X`.0.0 | 하위 호환이 깨지는 변경 |
| `minor` | X.`Y`.0 | 하위 호환되는 기능 추가 |
| `patch` | X.Y.`Z` | 하위 호환되는 버그 수정 |

라벨이 없거나 둘 이상이면 `Verify Version Label` 체크가 실패해 병합할 수 없다.

(`docs/*`·`chore/*` PR에는 라벨이 필요 없다.)

### 2-2. PR 본문 체크박스를 모두 채운다
PR 본문의 체크박스(`- [ ]`)는 **작성자가 완료한 항목을 전부 체크**한다. Key Changes 목록과 하단 Checklist가 모두 대상이다.

하나라도 미체크로 남으면 `Verify PR Checklist`가 실패해 병합할 수 없다. 즉, 모든 항목을 실제로 끝내고 체크한 뒤에야 병합이 열린다.

### 2-3. CI 체크를 통과시킨다
`feature/*` PR에는 아래가 붙는다. 전부 초록불이어야 병합된다.

- **Verify PR Checklist** — 미체크 체크박스가 없는지.

- **Verify Version Label** — 버전 라벨이 정확히 하나인지(§2-1).

- **Serialize Guard** — 지금 진행 중인 release/hotfix가 없는지(§4).

- **test (3.11 / 3.12 / 3.13)** — 세 파이썬 버전에서 테스트 통과.

### 2-4. 리뷰를 받는다
**사람이 코드를 검토하는 곳은 이 PR 하나뿐이다.** 승인 1개 + CI 초록불이면 병합할 수 있다.
이후 단계는 이 리뷰를 신뢰해 전부 무인으로 돌아간다.

---

## 3. 병합한 뒤에 벌어지는 일 (참고용)

당신이 할 일은 병합까지지만, 뒤 흐름을 알아두면 좋다.

1. `feature → develop`이 병합되면 파이프라인이 `release/vX.Y.Z` 브랜치를 **자동 생성**한다(아직 태그·배포 없음).
2. 릴리스 담당자가 "배포 준비 완료" 신호(수동 워크플로 실행)를 주면 태그가 찍히고
   `release → master`·`release → develop` PR이 자동으로 열려 무인 병합된다.
3. 두 병합이 끝나면 GitHub Release가 생성되고 PyPI로 배포된 뒤 release 브랜치가 삭제된다.

즉, 당신의 변경은 develop에 들어간 순간 다음 릴리스 후보가 된다. 배포 타이밍만 릴리스 담당의 판단이다.

---

## 4. "병합 버튼이 막혀 있어요"

### 진행 중인 release/hotfix가 있을 때
`Serialize Guard`가 실패한다. 파이프라인은 **release/hotfix를 한 번에 하나만** 허용한다
(버전 충돌·브랜치 꼬임 방지). 진행 중인 release가 finalize되어 브랜치가 삭제될 때까지 기다렸다가,
develop을 다시 받아 재실행하면 통과한다.

### 브랜치가 뒤처졌을 때(out of date)
누군가 먼저 병합해 `develop`이 움직이면 "Update branch"가 요구된다. develop을 머지해
최신으로 맞추면 CI가 다시 돌아 병합 가능해진다.

---

## 5. 핫픽스에 기여하기 (출시된 버전의 긴급 수정)

이미 배포된 버전에 심각한 버그가 있을 때만 해당한다. 일반 기여는 §1~2로 충분하다.

1. Actions 탭에서 **Make Hotfix Branch** 워크플로를 실행한다. master tip에서
   `hotfix/vX.Y.(Z+1)`을 자동으로 만든다(Z = master 도달 태그의 패치). develop이 아닌
   master에서 분기하는 이유는 미출시 기능이 딸려가지 않게 하기 위함이다.
   - 열려 있는 release/hotfix가 있으면 실패한다(1:1 직렬화, §4). 먼저 마무리한 뒤 다시 실행한다.

2. 만들어진 브랜치를 checkout해 수정하고 push한다. 핫픽스는 정의상 항상 PATCH라 버전 라벨이 필요 없다.

3. 이후 finalize·배포는 릴리스 담당이 진행한다(§3와 동일한 자동 흐름).

---

## 6. 자주 겪는 실패

| 증상 | 원인 / 해결 |
|------|------------|
| `Verify Version Label` 실패 | `feature/*` PR에 `major`/`minor`/`patch`를 정확히 하나 붙인다. |
| `Verify PR Checklist` 실패 | PR 본문의 `- [ ]`를 모두 체크한다. |
| `Serialize Guard` 실패 | 진행 중인 release/hotfix가 끝날 때까지 대기(§4). |
| "Update branch" 요구 | develop을 머지해 최신으로 맞춘다(§4). |
| 라벨을 붙였는데 여전히 실패 | 라벨을 바꾸면 체크가 재평가된다. 라벨이 정확히 하나인지 다시 확인. |
