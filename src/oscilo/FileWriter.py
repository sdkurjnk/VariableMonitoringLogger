import json


class FileWriter:
    def write(self, filename, history):
        with open(filename, "w", encoding="utf-8") as file:
            for entry in history:
                json_line = self._serialize_entry(entry)

                # repr()조차 실패해서 아예 표현 불가능한 엔트리는 파일 전체를 망가뜨리지 않도록 건너뛴다.
                # 이슈 #52 참고.
                if json_line is None:
                    continue

                file.write(json_line + "\n")

    def _serialize_entry(self, entry):
        # 일반적인 경우: 엔트리가 이미 그대로 JSON 직렬화 가능하다.
        try:
            return json.dumps(entry, ensure_ascii=False)
        except Exception:
            pass

        # 폴백: JSON 네이티브가 아닌 값(예: `data`의 커스텀 객체)을 repr()로 대체해
        # 나머지 필드는 보존하고 레코드 전체를 잃지 않는다.
        try:
            return json.dumps(entry, ensure_ascii=False, default=repr)
        except Exception:
            # repr() 폴백마저 실패(예: __repr__가 예외, 또는 default로도 처리 못 하는 dict key).
            # 이 엔트리 하나만 포기한다.
            return None