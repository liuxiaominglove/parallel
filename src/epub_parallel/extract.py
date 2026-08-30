"""XHTML -> 有序可译块（叶级段落/标题/列表项等）。"""

import re

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


def is_translatable_text(text):
    """文本是否值得翻译：非空、含字母、且不全是中文。"""
    t = " ".join(text.split()).strip()
    if not t:
        return False
    letters = _LETTER.findall(t)
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


def extract_blocks(soup):
    """返回按文档顺序排列的叶级可译块列表。

    叶级 = 候选标签内部不再嵌套其他候选标签，避免重复翻译
    （如 <blockquote><p>..</p></blockquote> 只译内层 <p>）。
    """
    candidates = [t for t in soup.find_all(True) if t.name in LEAF_TAGS]
    leaves = [t for t in candidates if not any(d.name in LEAF_TAGS for d in t.find_all(True))]
    result = []
    for tag in leaves:
        if _has_skip_ancestor(tag):
            continue
        if align.is_translated(tag):
            continue
        if not is_translatable_text(block_text(tag)):
            continue
        result.append(tag)
    return result
