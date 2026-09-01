"""Shared test fixtures: build a minimal EPUB using ebooklib (write-once is safe)."""

import zipfile

import pytest
from ebooklib import epub

SAMPLE_XHTML_1 = (
    "<h1>Chapter One</h1>"
    "<p>Hello world.</p>"
    "<p>Second para with <em>emphasis</em> and a <a href='http://example.com'>link</a>.</p>"
    "<ul><li>First item</li><li>Second item</li></ul>"
    "<blockquote>A quoted passage.</blockquote>"
    "<p>   </p>"
    "<p>12345</p>"
    "<pre><code>print('skip me')</code></pre>"
)

SAMPLE_XHTML_2 = (
    "<h1>Chapter Two</h1>"
    "<p>Another chapter paragraph.</p>"
)


@pytest.fixture
def sample_xhtml1():
    return SAMPLE_XHTML_1


@pytest.fixture
def epub_bytes():
    """Return bytes of a 2-chapter EPUB with spine order [chap_1, chap_2]."""

    book = epub.EpubBook()
    book.set_identifier("id-1")
    book.set_title("Test Book")
    book.set_language("en")
    book.add_author("Author")

    c1 = epub.EpubHtml(title="Chapter 1", file_name="chap_1.xhtml", lang="en")
    c1.content = SAMPLE_XHTML_1
    c2 = epub.EpubHtml(title="Chapter 2", file_name="chap_2.xhtml", lang="en")
    c2.content = SAMPLE_XHTML_2

    book.add_item(c1)
    book.add_item(c2)
    book.toc = (c1, c2)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1, c2]

    import io

    buf = io.BytesIO()
    epub.write_epub(buf, book, {})
    return buf.getvalue()


@pytest.fixture
def epub_path(tmp_path, epub_bytes):
    p = tmp_path / "sample.epub"
    p.write_bytes(epub_bytes)
    return p


def make_epub(tmp_path, chapters, name="sample.epub"):
    """Helper to build a fresh EPUB with arbitrary chapter contents."""
    book = epub.EpubBook()
    book.set_identifier("id-1")
    book.set_title("Test Book")
    book.set_language("en")
    book.add_author("Author")

    items = []
    for i, content in enumerate(chapters):
        c = epub.EpubHtml(title=f"Chapter {i+1}", file_name=f"chap_{i+1}.xhtml", lang="en")
        c.content = content
        book.add_item(c)
        items.append(c)

    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items

    import io

    buf = io.BytesIO()
    epub.write_epub(buf, book, {})
    p = tmp_path / name
    p.write_bytes(buf.getvalue())
    return p


# 各文档的 epub:type / data-type（文档级语义标记，用于过滤前后置页）
_TYPED_DOCS = {
    "chapter": '<section epub:type="chapter"><h1>Ch</h1><p>Body text.</p></section>',
    "index": '<section epub:type="index"><p>Index entry.</p></section>',
    "copyright": '<section epub:type="copyright-page"><p>Copyright.</p></section>',
    "titlepage": '<section epub:type="titlepage"><p>Title.</p></section>',
    "dedication": '<section epub:type="dedication"><p>For X.</p></section>',
    "part": '<div epub:type="part"><p>Part I.</p></div>',
    "colophon": '<section epub:type="colophon"><p>Colophon.</p></section>',
    "cover": '<div data-type="cover"><p>Cover title.</p></div>',
}


@pytest.fixture
def typed_epub_path(tmp_path):
    """8 个文档，各自带不同的文档级语义标记，顺序固定。"""
    return make_epub(tmp_path, list(_TYPED_DOCS.values()), "typed.epub")


# 无 epub:type 标记的前置页，靠内容启发式跳过
_FRONT_MATTER_DOCS = [
    "<h1>Chapter One</h1><p>Body text about dopamine and how it works.</p>",
    "<p>Copyright © 2018 Author Name</p><p>ISBN 978-1946885005</p><p>All rights reserved.</p>",
]


@pytest.fixture
def front_matter_epub_path(tmp_path):
    """2 个文档：正文 + 无标记版权页，用于测启发式跳过。"""
    return make_epub(tmp_path, _FRONT_MATTER_DOCS, "frontmatter.epub")
