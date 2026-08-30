import zipfile

import pytest

from epub_parallel import cli, epub_io
from epub_parallel.config import Config


class FakeTranslator:
    def translate_batch(self, texts):
        return [f"〔{t}〕" for t in texts]

    def cost(self, input_price, output_price):
        return 0.0


def test_default_output_path():
    assert cli.default_output_path("/a/b/foo.epub") == "/a/b/foo.bilingual.epub"
    assert cli.default_output_path("foo.EPUB") == "foo.bilingual.epub"


def test_default_checkpoint_path():
    assert cli.default_checkpoint_path("/a/b/foo.epub") == "/a/b/foo.checkpoint.json"


def test_dry_run_no_api_call(epub_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("Translator should not be created in dry-run")

    monkeypatch.setattr(cli.translate, "Translator", boom)
    rc = cli.main([str(epub_path), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "可译块总数" in out
    assert "dry-run" in out


def test_missing_key_returns_error(epub_path, monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    rc = cli.main([str(epub_path)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "API key" in err


def test_end_to_end_with_fake_translator(epub_path, tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    out_path = tmp_path / "out.epub"
    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: FakeTranslator())
    rc = cli.main([str(epub_path), "-o", str(out_path)])
    assert rc == 0
    assert out_path.exists()

    epub = epub_io.Epub(str(out_path))
    chap1 = [h for h in epub.documents() if "chap_1" in h][0]
    soup = epub.document_soup(chap1)
    assert len(soup.find_all("p", class_="cn-parallel")) == 6


def test_max_blocks_flag(epub_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class RecordingTranslator:
        def __init__(self, **kw):
            self.calls = []

        def translate_batch(self, texts):
            self.calls.extend(texts)
            return [f"〔{t}〕" for t in texts]

        def cost(self, input_price, output_price):
            return 0.0

    inst = None

    def make(**kw):
        nonlocal inst
        inst = RecordingTranslator(**kw)
        return inst

    monkeypatch.setattr(cli.translate, "Translator", make)
    out_path = tmp_path / "out.epub"
    rc = cli.main([str(epub_path), "-o", str(out_path), "--max-blocks", "4"])
    assert rc == 0
    assert len(inst.calls) == 4


def test_invalid_input_returns_error(tmp_path, capsys):
    rc = cli.main([str(tmp_path / "nope.epub")])
    assert rc == 1
    assert "错误" in capsys.readouterr().err


def test_dry_run_prints_estimate(epub_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("no translator in dry-run")

    monkeypatch.setattr(cli.translate, "Translator", boom)
    rc = cli.main([str(epub_path), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "预估剩余成本" in out


def test_max_cost_gate_aborts_without_yes(epub_path, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        return FakeTranslator()

    monkeypatch.setattr(cli.translate, "Translator", boom)
    # 剩余 8 块，估成本必大于 $0.000001，超限应中止
    rc = cli.main([str(epub_path), "--max-cost", "0.000001"])
    assert rc == 1
    assert called["n"] == 0  # 未创建 translator，未调 API
    assert "超过上限" in capsys.readouterr().err


def test_max_cost_gate_passes_with_yes(epub_path, tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: FakeTranslator())
    out_path = tmp_path / "out.epub"
    rc = cli.main([str(epub_path), "-o", str(out_path), "--max-cost", "0.000001", "--yes"])
    assert rc == 0
    assert out_path.exists()


def test_prints_actual_cost(epub_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: FakeTranslator())
    out_path = tmp_path / "out.epub"
    rc = cli.main([str(epub_path), "-o", str(out_path)])
    assert rc == 0
    assert "成本对比" in capsys.readouterr().out


def test_config_file_max_cost_applies(epub_path, tmp_path, monkeypatch, capsys):
    import json

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"max_cost": 0.000001}), encoding="utf-8")
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        return FakeTranslator()

    monkeypatch.setattr(cli.translate, "Translator", boom)
    # 未传 --max-cost，但从配置文件读到极小上限 → 门槛中止
    rc = cli.main([str(epub_path), "--config", str(cfg)])
    assert rc == 1
    assert called["n"] == 0
    assert "超过上限" in capsys.readouterr().err


def test_corrupted_config_file_returns_error(epub_path, tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "config.json"
    cfg.write_text("{ bad", encoding="utf-8")
    rc = cli.main([str(epub_path), "--config", str(cfg)])
    assert rc == 1
    assert "配置文件" in capsys.readouterr().err


def test_dry_run_reports_skipped_documents(typed_epub_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("no translator in dry-run")

    monkeypatch.setattr(cli.translate, "Translator", boom)
    rc = cli.main([str(typed_epub_path), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    # 8 文档，默认跳过 index/copyright-page/titlepage/dedication/colophon/cover 共 6 个
    assert "跳过 6" in out


def test_skip_types_flag_overrides(typed_epub_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("no translator in dry-run")

    monkeypatch.setattr(cli.translate, "Translator", boom)
    rc = cli.main([str(typed_epub_path), "--dry-run", "--skip-types", "index"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "跳过 1" in out


def test_progress_printed(epub_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: FakeTranslator())
    out_path = tmp_path / "out.epub"
    rc = cli.main([str(epub_path), "-o", str(out_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "进度" in out
    assert "[8/8]" in out


def test_failure_prints_resume_hint(epub_path, tmp_path, monkeypatch, capsys):
    from epub_parallel.translate import TranslateError

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class FailingTranslator:
        def __init__(self, **kw):
            pass

        def translate_batch(self, texts):
            raise TranslateError("模拟失败")

    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: FailingTranslator())
    out_path = tmp_path / "out.epub"
    rc = cli.main([str(epub_path), "-o", str(out_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "已翻译" in err
    assert "续跑" in err


def test_estimate_actual_comparison(epub_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: FakeTranslator())
    out_path = tmp_path / "out.epub"
    rc = cli.main([str(epub_path), "-o", str(out_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "预估" in out and "实际" in out
