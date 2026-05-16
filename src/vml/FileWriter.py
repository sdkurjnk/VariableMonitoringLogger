import json

class FileWriter:
    def write(self, filename, history):
        with open(filename, 'w', encoding='utf-8') as f:
            for entry in history:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')