"""XHTML -> 有序可译块（叶级段落/标题/列表项等）。"""

import re

from bs4 import NavigableString

from epub_parallel import align

# 参与翻译的块级标签
LEAF_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "blockquote", "dt", "dd", "figcaption", "td", "th", "caption",
}

# 这些祖先标签内的内容整体跳过（代码/脚本/样式等）
_SKIP_ANCESTORS = {"pre", "code", "script", "style", "title", "head", "noscript"}

_CJK = re.compile(r"[\u4e00-\u9fff]")
_LETTER = re.compile(r"[^\W\d_]")

# 整块为这些内容时无翻译价值：URL、邮箱、ISBN、裸域名、@账号（地址不在此列，保守留给文档级跳过）
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ISBN = re.compile(r"isbn[\s:-]*[0-9xX][0-9xX\- ]*", re.IGNORECASE)
# 裸域名（无 www/https 前缀），用保守 TLD 白名单避免误伤 U.S./Dr./e.g. 等缩写
_TLD = r"(?:com|net|org|edu|gov|io)"
_DOMAIN = re.compile(rf"\b[a-zA-Z0-9][a-zA-Z0-9-]*\.{_TLD}\b", re.IGNORECASE)
_HANDLE = re.compile(r"@[a-zA-Z0-9_]+")


def is_translatable_text(text):
    """文本是否值得翻译：非空、含字母、且不全是中文、且非纯 URL/邮箱/ISBN/域名/账号。"""
    t = " ".join(text.split()).strip()
    if not t:
        return False
    stripped = _ISBN.sub(" ", t)
    stripped = _URL.sub(" ", stripped)
    stripped = _EMAIL.sub(" ", stripped)
    stripped = _DOMAIN.sub(" ", stripped)
    stripped = _HANDLE.sub(" ", stripped)
    letters = _LETTER.findall(stripped)
    if not letters:
        return False
    if all(_CJK.match(c) for c in letters):
        return False
    return True


_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?，。；：！？、])")


def block_text(tag):
    """块的规范化文本（用于翻译）。"""
    text = " ".join(tag.get_text(" ", strip=True).split())
    return _SPACE_BEFORE_PUNCT.sub(r"\1", text)


def _has_skip_ancestor(tag):
    parent = tag.parent
    while parent is not None:
        if getattr(parent, "name", None) in _SKIP_ANCESTORS:
            return True
        parent = parent.parent
    return False


def is_front_matter(soup):
    """判断文档是否为版权页/目录页（无 epub:type 标记时的启发式，保守）。

    版权页：短文档且 copyright 与 ISBN / Library of Congress / © 在文档开头组合出现
    （位置约束 + 长度约束，避免误伤含 per-essay 版权行的长篇正文）。目录页：链接密集且块均短。
    """
    text = soup.get_text(" ", strip=True).lower()
    head = text[:300]
    if (
        len(text) < 1000
        and "copyright" in head
        and ("isbn" in head or "library of congress" in head or "©" in head)
    ):
        return True
    links = soup.find_all("a")
    if len(links) >= 8:
        blocks = extract_blocks(soup)
        if blocks and all(len(block_text(b)) < 40 for b in blocks):
            return True
    return False


_BIBLIO_TYPES = {"biblioentry"}


def _is_bibliography(tag):
    """块是否为书目条目（EPUB 3 标准语义 biblioentry），此类块不翻译。"""
    value = tag.get("epub:type")
    if value is None:
        return False
    types = value.split() if isinstance(value, str) else list(value)
    return bool(set(types) & _BIBLIO_TYPES)


def _span_from_run(tag, run):
    """把一段连续的直接文本 NavigableString 包进 <span>，保持原位。"""
    span = tag.new_tag("span")
    run[0].insert_before(span)
    for s in run:
        span.append(s.extract())
    return span


def _wrap_direct_text_runs(tag):
    """把 tag 的直接文本按连续段包成 <span>，返回 span 列表（保持文档序）。"""
    spans = []
    run = []
    for child in list(tag.children):
        if type(child) is NavigableString:
            run.append(child)
        else:
            if any(str(s).strip() for s in run):
                spans.append(_span_from_run(tag, run))
            run = []
    if any(str(s).strip() for s in run):
        spans.append(_span_from_run(tag, run))
    return spans


def extract_blocks(soup):
    """返回按文档顺序排列的可译块列表。

    叶级块 = 候选标签内部不再嵌套其他候选标签（如 <blockquote><p>..</p></blockquote>
    只译内层 <p>）；混合内容块（如 <li>Chapter 1<ul>…</ul></li>）的直接文本
    单独包成 <span> 成块，避免外层直接文本丢失。
    """
    candidates = [t for t in soup.find_all(True) if t.name in LEAF_TAGS]
    leaves = {id(t) for t in candidates if not any(d.name in LEAF_TAGS for d in t.find_all(True))}
    spans = set()
    for tag in candidates:
        if id(tag) in leaves:
            continue
        if _has_skip_ancestor(tag) or _is_bibliography(tag):
            continue
        if align.is_translated(tag):
            continue
        for span in _wrap_direct_text_runs(tag):
            spans.add(id(span))
    result = []
    for tag in soup.find_all(True):
        if id(tag) in spans:
            if not is_translatable_text(block_text(tag)):
                continue
            result.append(tag)
        elif tag.name in LEAF_TAGS and id(tag) in leaves:
            if _has_skip_ancestor(tag):
                continue
            if _is_bibliography(tag):
                continue
            if align.is_translated(tag):
                continue
            if not is_translatable_text(block_text(tag)):
                continue
            result.append(tag)
    return result
