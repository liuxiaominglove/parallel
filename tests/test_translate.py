import json

import pytest

from epub_parallel import translate
from epub_parallel.translate import TranslateError, Translator


class FakeResponse:
    def __init__(self, status_code=200, content=None, text=""):
        self.status_code = status_code
        self._content = content
        self.text = text

    def json(self):
        return self._content


def _ok_response(translations, usage=None):
    return FakeResponse(200, content={
        "choices": [{"message": {"content": json.dumps({"translations": translations})}}],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 20},
    })


@pytest.fixture
def translator():
    return Translator(api_key="test-key", backoff_base=0.0)


def test_missing_key_raises():
    with pytest.raises(TranslateError):
        Translator(api_key="")


def test_translate_batch_returns_ordered_list(monkeypatch, translator):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["headers"] = kwargs["headers"]
        return _ok_response(["你好，世界。", "猫坐在垫子上。"])

    monkeypatch.setattr(translate.requests, "post", fake_post)
    result = translator.translate_batch(["Hello world.", "The cat sat on the mat."])
    assert result == ["你好，世界。", "猫坐在垫子上。"]
    assert captured["url"].endswith("/chat/completions")
    body = json.loads(captured["json"]["messages"][1]["content"])
    assert body == ["Hello world.", "The cat sat on the mat."]
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["json"].get("thinking") == {"type": "disabled"}


def test_length_mismatch_retries_then_falls_back(monkeypatch, translator):
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        body = json.loads(kwargs["json"]["messages"][1]["content"])
        if len(body) > 1:
            return _ok_response(["只有一个"])  # 整批条数不匹配
        return _ok_response([f"译:{body[0]}"])  # 单段正确

    monkeypatch.setattr(translate.requests, "post", fake_post)
    result = translator.translate_batch(["a", "b"])
    assert result == ["译:a", "译:b"]
    # 整批重试 max_retries 次（条数不匹配被检测到），再加 2 次单段兜底
    assert calls["n"] == translator.max_retries + 2


def test_429_retries_then_succeeds(monkeypatch, translator):
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse(429, text="rate limited")
        return _ok_response(["好"])

    monkeypatch.setattr(translate.requests, "post", fake_post)
    assert translator.translate_batch(["ok"]) == ["好"]
    assert calls["n"] == 2


def test_invalid_json_retries(monkeypatch, translator):
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse(200, content={"choices": [{"message": {"content": "not json"}}]})
        return _ok_response(["好"])

    monkeypatch.setattr(translate.requests, "post", fake_post)
    assert translator.translate_batch(["ok"]) == ["好"]


def test_empty_batch_no_api_call(monkeypatch, translator):
    def fake_post(url, **kwargs):
        raise AssertionError("should not be called")

    monkeypatch.setattr(translate.requests, "post", fake_post)
    assert translator.translate_batch([]) == []


def test_network_error_retries(monkeypatch, translator):
    import requests as req

    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise req.ConnectionError("boom")
        return _ok_response(["好"])

    monkeypatch.setattr(translate.requests, "post", fake_post)
    assert translator.translate_batch(["ok"]) == ["好"]


def test_cost_accumulates_real_usage(monkeypatch, translator):
    monkeypatch.setattr(
        translate.requests, "post",
        lambda url, **kw: _ok_response(["好"], usage={"prompt_tokens": 1000, "completion_tokens": 500}),
    )
    translator.translate_batch(["ok"])
    # $0.14 / 1M input + $0.28 / 1M output
    assert translator.total_prompt_tokens == 1000
    assert translator.total_completion_tokens == 500
    assert translator.cost(0.14, 0.28) == pytest.approx(1000 / 1e6 * 0.14 + 500 / 1e6 * 0.28)


def test_cost_without_usage_field(monkeypatch, translator):
    monkeypatch.setattr(translate.requests, "post", lambda url, **kw: FakeResponse(200, content={
        "choices": [{"message": {"content": json.dumps({"translations": ["好"]})}}],
    }))
    translator.translate_batch(["ok"])
    assert translator.total_prompt_tokens == 0
    assert translator.cost(0.14, 0.28) == 0.0


def test_disable_thinking_off_omits_param(monkeypatch):
    t = Translator(api_key="k", disable_thinking=False, backoff_base=0.0)
    captured = {}

    def fake_post(url, **kw):
        captured["json"] = kw["json"]
        return _ok_response(["好"])

    monkeypatch.setattr(translate.requests, "post", fake_post)
    t.translate_batch(["ok"])
    assert "thinking" not in captured["json"]


def test_parse_translations_repairs_missing_comma():
    bad = '{"translations": ["第一句" \n "第二句" "第三句"]}'
    assert Translator._parse_translations(bad) == ["第一句", "第二句", "第三句"]


def test_parse_translations_accepts_valid_json():
    good = '{"translations": ["第一句", "第二句"]}'
    assert Translator._parse_translations(good) == ["第一句", "第二句"]


def test_malformed_json_repaired_in_attempt(monkeypatch):
    t = Translator(api_key="k", backoff_base=0.0)
    bad = '{"translations": ["好" "呀"]}'
    monkeypatch.setattr(translate.requests, "post", lambda url, **kw: FakeResponse(200, content={
        "choices": [{"message": {"content": bad}}],
    }))
    assert t.translate_batch(["x", "y"]) == ["好", "呀"]


def test_parse_translations_still_raises_on_unrepairable():
    import pytest as _pytest

    with _pytest.raises(Exception):
        Translator._parse_translations("{ totally broken")


def test_batch_falls_back_to_single_segments(monkeypatch):
    t = Translator(api_key="k", backoff_base=0.0, max_retries=2)

    def fake_post(url, **kw):
        body = json.loads(kw["json"]["messages"][1]["content"])
        if len(body) > 1:
            # 整批持续返回坏 JSON
            return FakeResponse(200, content={"choices": [{"message": {"content": "{ bad"}}]})
        return _ok_response([f"译:{body[0]}"])

    monkeypatch.setattr(translate.requests, "post", fake_post)
    result = t.translate_batch(["a", "b", "c"])
    assert result == ["译:a", "译:b", "译:c"]


def test_batch_success_does_not_fallback(monkeypatch):
    t = Translator(api_key="k", backoff_base=0.0, max_retries=3)
    single_calls = {"n": 0}

    def fake_post(url, **kw):
        body = json.loads(kw["json"]["messages"][1]["content"])
        if len(body) == 1:
            single_calls["n"] += 1
        return _ok_response([f"译:{s}" for s in body])

    monkeypatch.setattr(translate.requests, "post", fake_post)
    assert t.translate_batch(["a", "b", "c"]) == ["译:a", "译:b", "译:c"]
    assert single_calls["n"] == 0  # 整批成功，没触发逐段


def test_batch_fallback_single_also_fails_raises(monkeypatch):
    t = Translator(api_key="k", backoff_base=0.0, max_retries=1)

    def fake_post(url, **kw):
        return FakeResponse(200, content={"choices": [{"message": {"content": "{ bad"}}]})

    monkeypatch.setattr(translate.requests, "post", fake_post)
    with pytest.raises(TranslateError):
        t.translate_batch(["a", "b"])


def test_single_segment_failure_raises_directly(monkeypatch):
    t = Translator(api_key="k", backoff_base=0.0, max_retries=1)

    def fake_post(url, **kw):
        return FakeResponse(200, content={"choices": [{"message": {"content": "{ bad"}}]})

    monkeypatch.setattr(translate.requests, "post", fake_post)
    with pytest.raises(TranslateError):
        t.translate_batch(["a"])
