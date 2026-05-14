class FileWriter:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FileWriter, cls).__new__(cls)
        return cls._instance

    def write(self, filename, history):
        with open(filename, 'w', encoding='utf-8') as f:
            for entry in history:
                f.write(json.dumps(entry.to_dict()) + '\n')
