"""编排：提取 → 翻译（断点续跑）→ 插入 → 写出双语 EPUB。"""

from epub_parallel import align, epub_io, extract

CN_CSS = ".cn-parallel { color: #555; font-size: 0.92em; margin-top: 0.1em; margin-bottom: 0.5em; }"


def inject_style(soup):
    """把 .cn-parallel 样式注入文档 <head>（幂等）。"""
    if soup.find("style", string=lambda s: s and "cn-parallel" in s) is not None:
        return
    style = soup.new_tag("style")
    style["type"] = "text/css"
    style.string = CN_CSS
    head = soup.find("head")
    if head is not None:
        head.append(style)
    else:
        html = soup.find("html")
        if html is not None:
            html.insert(0, style)
        else:
            soup.append(style)


def count_blocks(epub, skip_types=()):
    """统计每个可译文档的块数量。"""
    return {
        href: len(extract.extract_blocks(epub.document_soup(href)))
        for href in translatable_documents(epub, skip_types)
    }


def translatable_documents(epub, skip_types=()):
    """返回排除 skip_types 语义类型的文档列表（按 spine 顺序）。"""
    skip = set(skip_types)
    return [href for href in epub.documents() if not (epub.document_types(href) & skip)]


def _doc_texts(epub, href):
    soup = epub.document_soup(href)
    blocks = extract.extract_blocks(soup)
    return [extract.block_text(b) for b in blocks]


def remaining_texts(epub, checkpoint, skip_types=()):
    """返回尚未翻译（checkpoint 之外的）块文本，按文档顺序。"""
    result = []
    for href in translatable_documents(epub, skip_types):
        texts = _doc_texts(epub, href)
        done = len(checkpoint.get_translations(href))
        result.extend(texts[done:])
    return result


def estimate_cost(texts, input_price, output_price):
    """粗估 token 与成本（美元）。输入按 ~4 字符/token，输出按 ~1.5 字符/token。"""
    if not texts:
        return 0, 0, 0.0
    chars = sum(len(t) for t in texts)
    in_tokens = chars / 4.0
    out_tokens = chars / 1.5
    cost = in_tokens / 1_000_000 * input_price + out_tokens / 1_000_000 * output_price
    return in_tokens, out_tokens, cost


def count_translated(epub, checkpoint, skip_types=()):
    """返回已翻译（checkpoint 中已有）的块数，按可译文档 clamp。"""
    count = 0
    for href in translatable_documents(epub, skip_types):
        texts = _doc_texts(epub, href)
        done = len(checkpoint.get_translations(href))
        count += min(done, len(texts))
    return count


def translate_all(epub, checkpoint, translator, config, max_blocks=None, on_progress=None):
    """翻译所有文档的缺失块，逐批写 checkpoint。

    返回 (新增翻译块数, 停止原因)，停止原因为 None / "max_blocks" / "max_cost"。
    on_progress(done, total, cost) 每批完成后回调：done=本次已完成块数，total=本次需翻总块数。
    """
    total = len(remaining_texts(epub, checkpoint, config.skip_types))
    budget = max_blocks
    new_count = 0
    for href in translatable_documents(epub, config.skip_types):
        texts = _doc_texts(epub, href)
        existing = checkpoint.get_translations(href)[: len(texts)]
        translations = list(existing)
        start = len(translations)
        while start < len(texts):
            if budget is not None and budget <= 0:
                return new_count, "max_blocks"
            batch = texts[start : start + config.batch_size]
            if budget is not None:
                batch = batch[:budget]
            new = translator.translate_batch(batch)
            translations.extend(new)
            start += len(batch)
            new_count += len(batch)
            if budget is not None:
                budget -= len(batch)
            checkpoint.set_translations(href, translations)
            checkpoint.save()
            if on_progress is not None:
                on_progress(new_count, total, translator.cost(config.input_price, config.output_price))
            if config.max_cost is not None and translator.cost(
                config.input_price, config.output_price
            ) >= config.max_cost:
                return new_count, "max_cost"
        checkpoint.set_translations(href, translations)
        checkpoint.save()
    return new_count, None


def build_output(epub, checkpoint, output_path, skip_types=()):
    """按 checkpoint 译文重建双语 EPUB，写入 output_path（跳过的文档字节原样保留）。"""
    modified = {}
    for href in translatable_documents(epub, skip_types):
        soup = epub.document_soup(href)
        blocks = extract.extract_blocks(soup)
        translations = checkpoint.get_translations(href)[: len(blocks)]
        inserted = 0
        for block, cn in zip(blocks, translations):
            if align.insert_translation(block, cn) is not None:
                inserted += 1
        if inserted:
            inject_style(soup)
        modified[href] = epub_io.serialize_xhtml(soup)
    epub.write(output_path, modified)
