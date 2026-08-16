import json


class FileWriter:
    def write(self, filename, history):
        with open(filename, "w", encoding="utf-8") as file:
            for entry in history:
                json_line = self._serialize_entry(entry)

                # repr()조차 실패해서 아예 표현 불가능한 엔트리는 파일 전체를
                # 망가뜨리지 않도록 건너뛴다. 이슈 #52 참고.
                if json_line is None:
                    continue

                file.write(json_line + "\n")

    def _serialize_entry(self, entry):
        # 일반적인 경우: 엔트리가 이미 그대로 JSON 직렬화 가능하다.
        try:
            return json.dumps(entry, ensure_ascii=False)
        except Exception:
            pass

        # 폴백: 엔트리 안에서 기본적으로 JSON 직렬화가 안 되는 값(예: `data`에
        # 담긴 평범한 커스텀 객체)을 repr()로 대체한다. 그러면 엔트리의 나머지
        # 필드(name/event/line/call_id/...)는 보존되고 레코드 전체를 잃지 않는다.
        try:
            return json.dumps(entry, ensure_ascii=False, default=repr)
        except Exception:
            # repr() 기반 폴백마저 실패한 경우(예: __repr__ 자체가 예외를
            # 던지거나, json이 `default`로도 처리 못 하는 타입의 dict key인
            # 경우)다. 이 엔트리 하나만 포기한다.
            return None