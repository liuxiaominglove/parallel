import json

import pytest

from epub_parallel.config import Config, ConfigError, load_config_file


def test_default_model_is_v4_flash():
    assert Config().model == "deepseek-v4-flash"


def test_default_prices_are_usd():
    cfg = Config()
    assert cfg.input_price == 0.14
    assert cfg.output_price == 0.28
    assert cfg.disable_thinking is True


def test_from_env_overrides(tmp_path):
    cfg = Config.from_env(
        config_path=str(tmp_path / "nope.json"),
        model="x", max_cost=1.5, input_price=0.5, output_price=1.0, disable_thinking=False,
    )
    assert cfg.model == "x"
    assert cfg.max_cost == 1.5
    assert cfg.input_price == 0.5
    assert cfg.output_price == 1.0
    assert cfg.disable_thinking is False


def test_from_env_ignores_none(tmp_path):
    cfg = Config.from_env(config_path=str(tmp_path / "nope.json"), max_cost=None, input_price=None)
    assert cfg.max_cost is None
    assert cfg.input_price == 0.14


def test_load_config_file_missing_returns_empty(tmp_path):
    assert load_config_file(str(tmp_path / "nope.json")) == {}


def test_load_config_file_reads_and_coerces(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"max_cost": 1.5, "batch_size": 10, "disable_thinking": False, "model": "m"}), encoding="utf-8")
    data = load_config_file(str(p))
    assert data["max_cost"] == 1.5
    assert data["batch_size"] == 10
    assert data["disable_thinking"] is False
    assert data["model"] == "m"


def test_load_config_file_corrupted_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config_file(str(p))


def test_load_config_file_non_object_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config_file(str(p))


def test_load_config_file_ignores_unknown_and_api_key(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"api_key": "sk-secret", "unknown_field": 123, "max_cost": 2.0}), encoding="utf-8")
    data = load_config_file(str(p))
    assert "api_key" not in data
    assert "unknown_field" not in data
    assert data["max_cost"] == 2.0


def test_from_env_config_file_overrides_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"max_cost": 3.0, "input_price": 0.5}), encoding="utf-8")
    cfg = Config.from_env(config_path=str(p))
    assert cfg.max_cost == 3.0
    assert cfg.input_price == 0.5
    assert cfg.output_price == 0.28  # 未在文件里，用代码默认


def test_from_env_cli_overrides_config_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"max_cost": 3.0}), encoding="utf-8")
    cfg = Config.from_env(config_path=str(p), max_cost=9.9)
    assert cfg.max_cost == 9.9


def test_default_skip_types():
    cfg = Config()
    assert "index" in cfg.skip_types
    assert "copyright-page" in cfg.skip_types
    assert "part" not in cfg.skip_types  # 用户确认 part 不跳


def test_skip_types_from_config_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"skip_types": ["index", "part"]}), encoding="utf-8")
    cfg = Config.from_env(config_path=str(p))
    assert cfg.skip_types == ("index", "part")


def test_skip_types_from_cli_override(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"skip_types": ["index"]}), encoding="utf-8")
    cfg = Config.from_env(config_path=str(p), skip_types=("cover",))
    assert cfg.skip_types == ("cover",)


def test_bool_string_false_coerced(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"disable_thinking": "false"}), encoding="utf-8")
    assert load_config_file(str(p))["disable_thinking"] is False


def test_bool_string_off_coerced(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"disable_thinking": "off"}), encoding="utf-8")
    assert load_config_file(str(p))["disable_thinking"] is False


def test_bool_native_false_stays_false(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"disable_thinking": False}), encoding="utf-8")
    assert load_config_file(str(p))["disable_thinking"] is False


def test_load_config_bad_numeric_value_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"batch_size": "abc"}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config_file(str(p))


def test_load_config_bad_tuple_value_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"skip_types": 123}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config_file(str(p))
