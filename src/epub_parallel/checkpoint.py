"""断点续跑：翻译结果缓存（JSON 落盘，原子写入）。"""

import json
import os
import tempfile


class CheckpointError(Exception):
    pass


class Checkpoint:
    """以 `{doc_href: [译文...]}` 缓存每个文档的翻译结果，顺序对齐提取块顺序。"""

    def __init__(self, path):
        self.path = path
        self.data = {"version": 1, "documents": {}}
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise CheckpointError(f"checkpoint 损坏: {self.path} ({e})") from e
        if not isinstance(data, dict) or "documents" not in data:
            raise CheckpointError(f"checkpoint 结构无效: {self.path}")
        self.data = data

    def get_translations(self, doc_href):
        doc = self.data["documents"].get(doc_href)
        if not doc:
            return []
        return doc.get("translations", [])

    def set_translations(self, doc_href, translations):
        self.data["documents"][doc_href] = {"translations": list(translations)}

    def save(self):
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".checkpoint-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
