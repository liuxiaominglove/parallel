"""DeepSeek 翻译客户端：批处理 + 重试 + JSON 解析校验。"""

import json
import re
import time

import requests

SYSTEM_PROMPT = (
    "You are a professional English-to-Simplified-Chinese translator. "
    "Translate each input string faithfully and naturally. "
    "Preserve proper names, numbers, code, and technical terms. "
    'Return ONLY a JSON object of the form {"translations": ["...", "..."]} '
    "with exactly one translation per input string, in the same order. "
    "The JSON must be strictly valid: escape any double quotes inside a translation "
    "as \\\" and keep each translation on a single line."
)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# 模型偶发在相邻字符串间漏掉逗号（"a" "b" -> 应为 "a", "b"），此处安全补回
_MISSING_COMMA = re.compile(r'"(\s+)"')


class TranslateError(Exception):
    """翻译失败（重试耗尽后仍失败）。"""


class Translator:
    def __init__(self, api_key, base_url="https://api.deepseek.com", model="deepseek-v4-flash",
                 temperature=0.2, timeout=60.0, max_retries=5, backoff_base=1.0,
                 disable_thinking=True):
        if not api_key:
            raise TranslateError("缺少 API key（环境变量 DEEPSEEK_API_KEY 未设置）")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.disable_thinking = disable_thinking
        self._endpoint = self.base_url + "/chat/completions"
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def translate_batch(self, texts):
        """翻译一批文本，返回同长度的译文列表。

        整批重试耗尽后，若仍失败且批次含多段，则逐段兜底重翻（只重翻坏段）。
        单段也失败则抛 TranslateError（系统级故障，靠 checkpoint 续跑）。
        """
        if not texts:
            return []
        payload = self._build_payload(texts)
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._attempt(payload, texts)
            except TranslateError as e:
                last_error = e
                if attempt == self.max_retries:
                    break
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))
        if len(texts) == 1:
            raise TranslateError(f"翻译失败（重试 {self.max_retries} 次后放弃）: {last_error}")
        return [self._translate_single(t) for t in texts]

    def _translate_single(self, text):
        """单段翻译（带重试），失败抛 TranslateError。"""
        payload = self._build_payload([text])
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._attempt(payload, [text])[0]
            except TranslateError as e:
                last_error = e
                if attempt == self.max_retries:
                    break
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))
        raise TranslateError(f"单段翻译失败（重试 {self.max_retries} 次后放弃）: {last_error}")

    def cost(self, input_price, output_price):
        """按累计真实 token 计算成本（美元）。"""
        return (
            self.total_prompt_tokens / 1_000_000 * input_price
            + self.total_completion_tokens / 1_000_000 * output_price
        )

    def _build_payload(self, texts):
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
            ],
            "temperature": self.temperature,
        }
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        return payload

    def _attempt(self, payload, texts):
        try:
            resp = requests.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise TranslateError(f"网络错误: {e}") from e

        if resp.status_code in RETRYABLE_STATUS or resp.status_code >= 500:
            raise TranslateError(f"HTTP {resp.status_code}")

        if resp.status_code != 200:
            raise TranslateError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            translations = self._parse_translations(content)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            raise TranslateError(f"响应解析失败: {e}") from e

        if not isinstance(translations, list) or len(translations) != len(texts):
            raise TranslateError(
                f"译文条数不匹配: 期望 {len(texts)}，得到 {len(translations) if isinstance(translations, list) else '非列表'}"
            )

        usage = data.get("usage") or {}
        self.total_prompt_tokens += int(usage.get("prompt_tokens", 0))
        self.total_completion_tokens += int(usage.get("completion_tokens", 0))

        return [str(t) for t in translations]

    @staticmethod
    def _parse_translations(content):
        """解析模型返回的 translations；JSON 坏掉时先补漏掉的逗号再试一次。"""
        try:
            return json.loads(content)["translations"]
        except (json.JSONDecodeError, KeyError):
            repaired = _MISSING_COMMA.sub(r'",\1"', content)
            return json.loads(repaired)["translations"]
