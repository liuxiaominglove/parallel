import zipfile

import pytest

from epub_parallel import epub_io, pipeline
from epub_parallel.checkpoint import Checkpoint
from epub_parallel.config import Config


class FakeTranslator:
    def __init__(self):
        self.calls = []

    def translate_batch(self, texts):
        self.calls.extend(texts)
        return [f"〔{t}〕" for t in texts]

    def cost(self, input_price, output_price):
        return len(self.calls) * 0.0001


@pytest.fixture
def fake_translator():
    return FakeTranslator()


def _read_doc(path, href):
    with zipfile.ZipFile(path) as z:
        return z.read(href)


def test_count_blocks(epub_path):
    epub = epub_io.Epub(str(epub_path))
    counts = pipeline.count_blocks(epub)
    key1 = [k for k in counts if "chap_1" in k][0]
    assert counts[key1] == 6  # h1 + 2p + 2li + blockquote (skip empty/12345/pre)


def test_translate_all_build_output_end_to_end(epub_path, tmp_path, fake_translator):
    config = Config(batch_size=3)
    ck_path = tmp_path / "ck.json"
    out_path = tmp_path / "out.epub"

    epub = epub_io.Epub(str(epub_path))
    n, reason = pipeline.translate_all(epub, Checkpoint(str(ck_path)), fake_translator, config)
    assert n > 0
    assert reason is None
    pipeline.build_output(epub, Checkpoint(str(ck_path)), str(out_path))

    epub2 = epub_io.Epub(str(out_path))
    chap1 = [h for h in epub2.documents() if "chap_1" in h][0]
    soup = epub2.document_soup(chap1)
    cn_ps = soup.find_all("p", class_="cn-parallel")
    assert len(cn_ps) == 6
    # 每个英文段后紧跟对应译文
    en_p = soup.find_all("p")
    assert any("Hello world." in p.get_text() for p in en_p)
    assert any("〔Hello world.〕" in p.get_text() for p in cn_ps)


def test_resume_skips_already_translated(epub_path, tmp_path, fake_translator):
    config = Config(batch_size=10)
    ck_path = tmp_path / "ck.json"
    out_path = tmp_path / "out.epub"
    epub = epub_io.Epub(str(epub_path))

    # 第一次跑 2 块后中断（max_blocks=2）
    pipeline.translate_all(epub, Checkpoint(str(ck_path)), fake_translator, config, max_blocks=2)
    first_calls = list(fake_translator.calls)

    # 续跑
    pipeline.translate_all(epub, Checkpoint(str(ck_path)), fake_translator, config)
    # 之前译过的块不再进入 API
    assert fake_translator.calls[: len(first_calls)] == first_calls
    pipeline.build_output(epub, Checkpoint(str(ck_path)), str(out_path))

    epub2 = epub_io.Epub(str(out_path))
    chap1 = [h for h in epub2.documents() if "chap_1" in h][0]
    assert len(epub2.document_soup(chap1).find_all("p", class_="cn-parallel")) == 6


def test_max_blocks_limits_total(epub_path, tmp_path, fake_translator):
    config = Config(batch_size=10)
    epub = epub_io.Epub(str(epub_path))
    n, reason = pipeline.translate_all(
        epub, Checkpoint(str(tmp_path / "ck.json")), fake_translator, config, max_blocks=3
    )
    assert n == 3
    assert reason == "max_blocks"
    assert len(fake_translator.calls) == 3


class CostTranslator:
    """每批固定消耗一定 token，用于测试成本上限。"""

    def __init__(self, prompt=0, completion_per_batch=1000):
        self.prompt = prompt
        self.completion_per_batch = completion_per_batch
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.calls = 0

    def translate_batch(self, texts):
        self.calls += 1
        self.total_prompt_tokens += self.prompt
        self.total_completion_tokens += self.completion_per_batch * len(texts)
        return [f"〔{t}〕" for t in texts]

    def cost(self, input_price, output_price):
        return (
            self.total_prompt_tokens / 1e6 * input_price
            + self.total_completion_tokens / 1e6 * output_price
        )


def test_max_cost_stops_early_and_writes_partial(epub_path, tmp_path):
    # 每块输出 1000 token * $0.28/1M = $0.00028/块；batch_size=1，上限 $0.0005 => 第 2 块后触顶
    config = Config(batch_size=1, max_cost=0.0005, input_price=0.14, output_price=0.28)
    ck_path = tmp_path / "ck.json"
    out_path = tmp_path / "out.epub"
    translator = CostTranslator(completion_per_batch=1000)

    epub = epub_io.Epub(str(epub_path))
    n, reason = pipeline.translate_all(epub, Checkpoint(str(ck_path)), translator, config)
    assert reason == "max_cost"
    assert n == 2  # 第 2 块译完即触顶

    # 写出已译部分（前 2 块）
    checkpoint = Checkpoint(str(ck_path))
    pipeline.build_output(epub, checkpoint, str(out_path))
    epub2 = epub_io.Epub(str(out_path))
    chap1 = [h for h in epub2.documents() if "chap_1" in h][0]
    assert len(epub2.document_soup(chap1).find_all("p", class_="cn-parallel")) == 2

    # 续跑：调大上限，只翻剩余块（不重复）
    config.max_cost = None
    n2, reason2 = pipeline.translate_all(epub, Checkpoint(str(ck_path)), translator, config)
    assert reason2 is None
    assert translator.calls == 2 + 6  # 前面译了 2 块，续跑译剩余 6 块


def test_no_max_cost_returns_none_reason(epub_path, tmp_path, fake_translator):
    config = Config(batch_size=10)  # max_cost=None
    epub = epub_io.Epub(str(epub_path))
    n, reason = pipeline.translate_all(
        epub, Checkpoint(str(tmp_path / "ck.json")), fake_translator, config
    )
    assert reason is None
    assert n == 8  # chap_1 6 块 + chap_2 2 块


def test_estimate_cost():
    in_tokens, out_tokens, cost = pipeline.estimate_cost(
        ["Hello world.", "A longer sentence with more words."], 0.14, 0.28
    )
    chars = len("Hello world.") + len("A longer sentence with more words.")
    assert in_tokens == pytest.approx(chars / 4.0)
    assert out_tokens == pytest.approx(chars / 1.5)
    assert cost == pytest.approx(in_tokens / 1e6 * 0.14 + out_tokens / 1e6 * 0.28)


def test_estimate_cost_empty():
    assert pipeline.estimate_cost([], 0.14, 0.28) == (0, 0, 0.0)


def test_remaining_texts_excludes_done(epub_path, tmp_path):
    epub = epub_io.Epub(str(epub_path))
    checkpoint = Checkpoint(str(tmp_path / "ck.json"))
    total = pipeline.remaining_texts(epub, checkpoint)
    assert len(total) == 8
    # 标记 chap_1 的前 2 块已译
    chap1 = [h for h in epub.documents() if "chap_1" in h][0]
    checkpoint.set_translations(chap1, ["一", "二"])
    remaining = pipeline.remaining_texts(epub, checkpoint)
    assert len(remaining) == 6


def test_translatable_documents_filters_by_type(typed_epub_path):
    epub = epub_io.Epub(str(typed_epub_path))
    docs = epub.documents()  # chapter,index,copyright,titlepage,dedication,part,colophon,cover
    result = pipeline.translatable_documents(epub, ("index",))
    assert docs[1] not in result
    assert docs[0] in result
    assert len(result) == 7


def test_translatable_documents_empty_skip_keeps_all(typed_epub_path):
    epub = epub_io.Epub(str(typed_epub_path))
    assert len(pipeline.translatable_documents(epub, ())) == len(epub.documents())


def test_translatable_documents_multiple_types(typed_epub_path):
    epub = epub_io.Epub(str(typed_epub_path))
    docs = epub.documents()
    result = pipeline.translatable_documents(epub, ("index", "copyright-page", "cover"))
    assert docs[1] not in result and docs[2] not in result and docs[7] not in result
    assert len(result) == 5


def test_count_blocks_skips_types(typed_epub_path):
    epub = epub_io.Epub(str(typed_epub_path))
    counts = pipeline.count_blocks(epub, skip_types=("index",))
    keys = " ".join(counts.keys())
    assert "chap_2" not in keys  # index 文档是第 2 个
    assert sum(counts.values()) == 8  # 9 块去掉 index 的 1 块


def test_translate_all_skips_documents(typed_epub_path, tmp_path, fake_translator):
    config = Config(batch_size=10, skip_types=("index",))
    epub = epub_io.Epub(str(typed_epub_path))
    ck = Checkpoint(str(tmp_path / "ck.json"))
    pipeline.translate_all(epub, ck, fake_translator, config)
    joined = " ".join(fake_translator.calls)
    assert "Index entry." not in joined
    assert "Body text." in joined


def test_build_output_leaves_skipped_docs_untouched(typed_epub_path, tmp_path, fake_translator):
    config = Config(batch_size=10, skip_types=("index",))
    epub = epub_io.Epub(str(typed_epub_path))
    ck = Checkpoint(str(tmp_path / "ck.json"))
    pipeline.translate_all(epub, ck, fake_translator, config)
    out = tmp_path / "out.epub"
    pipeline.build_output(epub, ck, str(out), skip_types=config.skip_types)

    index_href = epub.documents()[1]
    out_epub = epub_io.Epub(str(out))
    # 跳过的 index 文档字节与输入一致
    assert out_epub.document_bytes(index_href) == epub.document_bytes(index_href)
    # 正文文档被翻译
    chapter_href = epub.documents()[0]
    assert b"cn-parallel" in out_epub.document_bytes(chapter_href)


def test_translate_all_calls_progress_callback(epub_path, tmp_path, fake_translator):
    config = Config(batch_size=3)  # 8 块 -> 批次 3,3,2
    epub = epub_io.Epub(str(epub_path))
    ck = Checkpoint(str(tmp_path / "ck.json"))
    progress = []
    n, reason = pipeline.translate_all(
        epub, ck, fake_translator, config, on_progress=lambda d, t, c: progress.append((d, t, c))
    )
    assert reason is None
    assert [p[0] for p in progress] == [3, 6, 8]
    assert all(p[1] == 8 for p in progress)
    # cost 随进度递增
    assert [p[2] for p in progress] == sorted(p[2] for p in progress)


def test_translate_all_no_progress_callback_ok(epub_path, tmp_path, fake_translator):
    config = Config(batch_size=10)
    epub = epub_io.Epub(str(epub_path))
    n, reason = pipeline.translate_all(epub, Checkpoint(str(tmp_path / "ck.json")), fake_translator, config)
    assert reason is None and n == 8


def test_progress_not_called_when_nothing_to_do(epub_path, tmp_path, fake_translator):
    config = Config(batch_size=10)
    epub = epub_io.Epub(str(epub_path))
    ck_path = str(tmp_path / "ck.json")
    # 先全译一遍
    pipeline.translate_all(epub, Checkpoint(ck_path), fake_translator, config)
    # 再跑：无剩余，不应调进度回调
    called = []
    pipeline.translate_all(epub, Checkpoint(ck_path), fake_translator, config, on_progress=lambda *a: called.append(a))
    assert called == []


def test_progress_stops_at_max_blocks(epub_path, tmp_path, fake_translator):
    config = Config(batch_size=10)
    epub = epub_io.Epub(str(epub_path))
    progress = []
    n, reason = pipeline.translate_all(
        epub, Checkpoint(str(tmp_path / "ck.json")), fake_translator, config,
        max_blocks=3, on_progress=lambda d, t, c: progress.append((d, t, c))
    )
    assert reason == "max_blocks"
    assert progress[-1][0] == 3  # done 停在截断处


def test_count_translated_empty_checkpoint(epub_path, tmp_path):
    epub = epub_io.Epub(str(epub_path))
    assert pipeline.count_translated(epub, Checkpoint(str(tmp_path / "ck.json"))) == 0


def test_count_translated_partial(epub_path, tmp_path):
    epub = epub_io.Epub(str(epub_path))
    ck = Checkpoint(str(tmp_path / "ck.json"))
    chap1 = [h for h in epub.documents() if "chap_1" in h][0]
    ck.set_translations(chap1, ["一", "二", "三"])
    assert pipeline.count_translated(epub, ck) == 3


def test_count_translated_clamps_overfull(epub_path, tmp_path):
    epub = epub_io.Epub(str(epub_path))
    ck = Checkpoint(str(tmp_path / "ck.json"))
    chap1 = [h for h in epub.documents() if "chap_1" in h][0]
    ck.set_translations(chap1, ["一"] * 20)  # chap_1 实际只有 6 块
    assert pipeline.count_translated(epub, ck) == 6


def test_count_translated_skips_types(typed_epub_path, tmp_path):
    epub = epub_io.Epub(str(typed_epub_path))
    ck = Checkpoint(str(tmp_path / "ck.json"))
    # 给 index 文档（第 2 个）设翻译
    index_href = epub.documents()[1]
    ck.set_translations(index_href, ["索引"])
    assert pipeline.count_translated(epub, ck, skip_types=("index",)) == 0


def test_build_injects_style(epub_path, tmp_path, fake_translator):
    config = Config(batch_size=20)
    epub = epub_io.Epub(str(epub_path))
    ck_path = tmp_path / "ck.json"
    out_path = tmp_path / "out.epub"
    pipeline.translate_all(epub, Checkpoint(str(ck_path)), fake_translator, config)
    pipeline.build_output(epub, Checkpoint(str(ck_path)), str(out_path))
    epub2 = epub_io.Epub(str(out_path))
    chap1 = [h for h in epub2.documents() if "chap_1" in h][0]
    soup = epub2.document_soup(chap1)
    style = soup.find("style")
    assert style is not None and "cn-parallel" in style.get_text()


def test_build_no_duplicate_on_rebuild(epub_path, tmp_path, fake_translator):
    config = Config(batch_size=20)
    epub = epub_io.Epub(str(epub_path))
    ck_path = tmp_path / "ck.json"
    out_path = tmp_path / "out.epub"
    checkpoint = Checkpoint(str(ck_path))
    pipeline.translate_all(epub, checkpoint, fake_translator, config)
    pipeline.build_output(epub, checkpoint, str(out_path))
    # 从输入重新构建（checkpoint 不变），不应重复插入
    pipeline.build_output(epub, checkpoint, str(out_path))
    epub2 = epub_io.Epub(str(out_path))
    chap1 = [h for h in epub2.documents() if "chap_1" in h][0]
    assert len(epub2.document_soup(chap1).find_all("p", class_="cn-parallel")) == 6
