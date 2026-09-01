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


def test_max_cost_soft_hint_continues(epub_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        return FakeTranslator()

    monkeypatch.setattr(cli.translate, "Translator", boom)
    out_path = tmp_path / "out.epub"
    rc = cli.main([str(epub_path), "-o", str(out_path), "--max-cost", "0.000001"])
    assert rc == 0
    assert called["n"] == 1  # 软提示，仍创建 translator 继续
    assert "超过上限" in capsys.readouterr().out


def test_prints_actual_cost(epub_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: FakeTranslator())
    out_path = tmp_path / "out.epub"
    rc = cli.main([str(epub_path), "-o", str(out_path)])
    assert rc == 0
    assert "成本对比" in capsys.readouterr().out


def test_config_file_max_cost_soft_hint(epub_path, tmp_path, monkeypatch, capsys):
    import json

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"max_cost": 0.000001}), encoding="utf-8")
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        return FakeTranslator()

    monkeypatch.setattr(cli.translate, "Translator", boom)
    out_path = tmp_path / "out.epub"
    # 未传 --max-cost，但从配置文件读到极小上限 → 软提示继续，运行时真实门禁兜底
    rc = cli.main([str(epub_path), "-o", str(out_path), "--config", str(cfg)])
    assert rc == 0
    assert called["n"] == 1
    assert "超过上限" in capsys.readouterr().out


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


def test_skip_types_empty_string_skips_nothing(typed_epub_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("no translator in dry-run")

    monkeypatch.setattr(cli.translate, "Translator", boom)
    rc = cli.main([str(typed_epub_path), "--dry-run", "--skip-types", ""])
    out = capsys.readouterr().out
    assert rc == 0
    assert "跳过 0" in out


def test_output_same_as_input_rejected(epub_path, tmp_path, monkeypatch, capsys):
    import shutil

    target = tmp_path / "same.epub"
    shutil.copyfile(str(epub_path), str(target))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: FakeTranslator())
    rc = cli.main([str(target), "-o", str(target)])
    assert rc == 1
    assert "相同" in capsys.readouterr().err


def test_progress_printed(epub_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: FakeTranslator())
    out_path = tmp_path / "out.epub"
    rc = cli.main([str(epub_path), "-o", str(out_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "进度" in out
    assert "[8/8]" in out


def test_progress_throttled_when_not_tty(epub_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: FakeTranslator())
    out_path = tmp_path / "out.epub"
    # 8 块分 4 批，非 TTY（capsys 下 isatty=False）只应在 done==total 时打一行
    rc = cli.main([str(epub_path), "-o", str(out_path), "--batch-size", "2"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("进度") == 1
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


def test_warnings_printed(epub_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class WarningTranslator:
        def __init__(self, **kw):
            self.warnings = ["译文与原文相同: foo"]

        def translate_batch(self, texts):
            return [f"〔{t}〕" for t in texts]

        def cost(self, input_price, output_price):
            return 0.0

    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: WarningTranslator())
    out_path = tmp_path / "out.epub"
    rc = cli.main([str(epub_path), "-o", str(out_path)])
    assert rc == 0
    assert "质检告警" in capsys.readouterr().out


def test_no_warnings_not_printed(epub_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli.translate, "Translator", lambda **kw: FakeTranslator())
    out_path = tmp_path / "out.epub"
    rc = cli.main([str(epub_path), "-o", str(out_path)])
    assert rc == 0
    assert "质检告警" not in capsys.readouterr().out
