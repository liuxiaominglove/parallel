import json

import pytest

from epub_parallel.checkpoint import Checkpoint, CheckpointError


def test_new_checkpoint_empty(tmp_path):
    cp = Checkpoint(str(tmp_path / "ck.json"))
    assert cp.get_translations("EPUB/chap_1.xhtml") == []


def test_set_get_roundtrip(tmp_path):
    cp = Checkpoint(str(tmp_path / "ck.json"))
    cp.set_translations("EPUB/chap_1.xhtml", ["你好。", "第二句。"])
    assert cp.get_translations("EPUB/chap_1.xhtml") == ["你好。", "第二句。"]


def test_save_and_reload_persists(tmp_path):
    p = tmp_path / "ck.json"
    cp = Checkpoint(str(p))
    cp.set_translations("EPUB/a.xhtml", ["一"])
    cp.save()

    cp2 = Checkpoint(str(p))
    assert cp2.get_translations("EPUB/a.xhtml") == ["一"]
    assert cp2.get_translations("EPUB/b.xhtml") == []


def test_save_is_valid_json(tmp_path):
    p = tmp_path / "ck.json"
    cp = Checkpoint(str(p))
    cp.set_translations("EPUB/a.xhtml", ["译文"])
    cp.save()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["documents"]["EPUB/a.xhtml"]["translations"] == ["译文"]


def test_corrupted_json_raises(tmp_path):
    p = tmp_path / "ck.json"
    p.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(CheckpointError):
        Checkpoint(str(p))


def test_invalid_structure_raises(tmp_path):
    p = tmp_path / "ck.json"
    p.write_text('{"nope": true}', encoding="utf-8")
    with pytest.raises(CheckpointError):
        Checkpoint(str(p))


def test_partial_resume_alignment(tmp_path):
    p = tmp_path / "ck.json"
    cp = Checkpoint(str(p))
    cp.set_translations("EPUB/a.xhtml", ["一", "二"])
    cp.save()

    cp2 = Checkpoint(str(p))
    existing = cp2.get_translations("EPUB/a.xhtml")
    assert len(existing) == 2
    # 续跑：追加第三段
    existing.append("三")
    cp2.set_translations("EPUB/a.xhtml", existing)
    cp2.save()
    assert Checkpoint(str(p)).get_translations("EPUB/a.xhtml") == ["一", "二", "三"]


def test_non_utf8_checkpoint_raises(tmp_path):
    p = tmp_path / "ck.json"
    p.write_bytes(b"\xff\xfe\x00garbage")
    with pytest.raises(CheckpointError):
        Checkpoint(str(p))


def test_documents_null_raises(tmp_path):
    p = tmp_path / "ck.json"
    p.write_text('{"documents": null}', encoding="utf-8")
    with pytest.raises(CheckpointError):
        Checkpoint(str(p))


def test_documents_entry_not_dict_raises(tmp_path):
    p = tmp_path / "ck.json"
    p.write_text('{"documents": {"a.xhtml": "not-a-dict"}}', encoding="utf-8")
    with pytest.raises(CheckpointError):
        Checkpoint(str(p))


def test_translations_not_list_raises(tmp_path):
    p = tmp_path / "ck.json"
    p.write_text('{"documents": {"a.xhtml": {"translations": "nope"}}}', encoding="utf-8")
    with pytest.raises(CheckpointError):
        Checkpoint(str(p))


def test_save_io_error_wrapped(monkeypatch, tmp_path):
    cp = Checkpoint(str(tmp_path / "ck.json"))
    cp.set_translations("EPUB/a.xhtml", ["一"])

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("epub_parallel.checkpoint.os.replace", boom)
    with pytest.raises(CheckpointError):
        cp.save()
