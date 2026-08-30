from bs4 import BeautifulSoup

from epub_parallel import extract


def _soup(html):
    return BeautifulSoup(html, "html.parser")


def _texts(blocks):
    return [extract.block_text(b) for b in blocks]


def test_extract_returns_ordered_translatable_leaves():
    soup = _soup(
        "<h1>Chapter One</h1>"
        "<p>Hello world.</p>"
        "<p>Second para.</p>"
    )
    blocks = extract.extract_blocks(soup)
    assert _texts(blocks) == ["Chapter One", "Hello world.", "Second para."]


def test_extract_skips_script_style_code_and_pre():
    soup = _soup(
        "<p>Keep me.</p>"
        "<script>var x = 1;</script>"
        "<style>.a{color:red}</style>"
        "<pre><code>print('skip')</code></pre>"
        "<p>Keep me too.</p>"
    )
    assert _texts(extract.extract_blocks(soup)) == ["Keep me.", "Keep me too."]


def test_extract_skips_empty_and_numeric_only():
    soup = _soup("<p>   </p><p>12345</p><p>Real text.</p><p>&nbsp;</p>")
    assert _texts(extract.extract_blocks(soup)) == ["Real text."]


def test_extract_skips_pure_cjk_blocks():
    soup = _soup("<p>这是一段中文。</p><p>English here.</p>")
    assert _texts(extract.extract_blocks(soup)) == ["English here."]


def test_extract_nested_blockquote_only_leaf_translated():
    soup = _soup("<blockquote><p>Inner para.</p>tail</blockquote><p>Outer.</p>")
    # blockquote contains a <p>, so only the inner <p> and the outer <p> are leaves
    assert _texts(extract.extract_blocks(soup)) == ["Inner para.", "Outer."]


def test_extract_inline_tags_kept_in_text():
    soup = _soup("<p>Hello <em>world</em> and <a href='x'>link</a>.</p>")
    blocks = extract.extract_blocks(soup)
    assert extract.block_text(blocks[0]) == "Hello world and link."


def test_extract_handles_li_td_th():
    soup = _soup("<ul><li>Item one</li><li>Item two</li></ul><table><tr><td>Cell</td></tr></table>")
    assert _texts(extract.extract_blocks(soup)) == ["Item one", "Item two", "Cell"]


def test_is_translatable_text():
    assert extract.is_translatable_text("Hello world.") is True
    assert extract.is_translatable_text("   ") is False
    assert extract.is_translatable_text("123 456 !!!") is False
    assert extract.is_translatable_text("这是一段中文。") is False
    assert extract.is_translatable_text("Hello 123.") is True


def test_extract_skips_already_translated_sibling():
    soup = _soup("<p>Hello.</p><p class='cn-parallel'>你好</p><p>Second.</p>")
    assert _texts(extract.extract_blocks(soup)) == ["Second."]


def test_extract_skips_partially_translated():
    soup = _soup(
        "<p>One.</p><p class='cn-parallel'>一</p>"
        "<p>Two.</p><p class='cn-parallel'>二</p>"
        "<p>Three.</p>"
    )
    assert _texts(extract.extract_blocks(soup)) == ["Three."]


def test_extract_skips_translated_li():
    soup = _soup("<ul><li>Item<p class='cn-parallel'>项</p></li><li>Other</li></ul>")
    assert _texts(extract.extract_blocks(soup)) == ["Other"]


def test_extract_bilingual_file_returns_empty():
    soup = _soup("<p>Hello.</p><p class='cn-parallel'>你好</p><p>World.</p><p class='cn-parallel'>世界</p>")
    assert extract.extract_blocks(soup) == []
