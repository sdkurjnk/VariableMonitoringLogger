import json


class FileWriter:
    def write(self, filename, history):
        with open(filename, "w", encoding="utf-8") as file:
            for entry in history:
                # Write each history entry as one JSONL record.
                json_line = json.dumps(entry, ensure_ascii=False)
                file.write(json_line + "\n")