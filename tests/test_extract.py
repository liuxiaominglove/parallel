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
    # blockquote 的直接文本 "tail" 也应译（不再丢失），内层 <p> 与外部 <p> 仍分别译
    assert _texts(extract.extract_blocks(soup)) == ["Inner para.", "tail", "Outer."]


def test_extract_mixed_content_direct_text_captured():
    soup = _soup("<li>Chapter 1<ul><li>Section A</li></ul></li>")
    assert _texts(extract.extract_blocks(soup)) == ["Chapter 1", "Section A"]


def test_extract_mixed_content_blockquote_direct_text():
    soup = _soup("<blockquote>intro line<p>Body.</p></blockquote>")
    assert _texts(extract.extract_blocks(soup)) == ["intro line", "Body."]


def test_extract_does_not_wrap_comments_into_spans():
    from bs4 import Comment

    soup = _soup("<li>Chapter 1<!-- note --><ul><li>Section A</li></ul></li>")
    assert _texts(extract.extract_blocks(soup)) == ["Chapter 1", "Section A"]
    comment = soup.find(string=lambda s: isinstance(s, Comment))
    assert comment is not None
    assert comment.parent.name != "span"


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


def test_is_translatable_text_skips_urls_emails_isbn():
    assert extract.is_translatable_text("https://example.com") is False
    assert extract.is_translatable_text("www.benbellabooks.com") is False
    assert extract.is_translatable_text("feedback@benbellabooks.com") is False
    assert extract.is_translatable_text("ISBN 978-1946885005") is False
    assert extract.is_translatable_text("Visit https://x.com for details") is True
    assert extract.is_translatable_text("10440 N. Central Expressway, Suite 800") is True


def test_is_translatable_text_skips_bare_domain_and_handle():
    assert extract.is_translatable_text("SimonandSchuster.com") is False
    assert extract.is_translatable_text("@simonbooks") is False
    assert extract.is_translatable_text("Follow us @simonbooks") is True
    assert extract.is_translatable_text("Visit simonandschuster.com today") is True


def test_is_translatable_text_not_confused_by_abbreviations():
    assert extract.is_translatable_text("U.S. Army") is True
    assert extract.is_translatable_text("Dr. Smith wrote a book.") is True
    assert extract.is_translatable_text("e.g. for example") is True


def test_extract_skips_url_and_email_blocks():
    soup = _soup(
        "<p>See https://example.com for more.</p>"
        "<p>feedback@x.com</p>"
        "<p>Real text.</p>"
    )
    assert _texts(extract.extract_blocks(soup)) == ["See https://example.com for more.", "Real text."]


def test_extract_skips_biblioentry_blocks():
    soup = _soup(
        '<ol class="biblist">'
        '<li epub:type="biblioentry">Wallen and Lloyd, "Female Sexual Arousal."</li>'
        "<li>Normal list item to translate.</li>"
        "</ol>"
    )
    assert _texts(extract.extract_blocks(soup)) == ["Normal list item to translate."]


def test_is_front_matter_copyright_page():
    soup = _soup(
        "<p>Copyright © 2018 Daniel Z. Lieberman</p>"
        "<p>ISBN 978-1946885005</p>"
        "<p>All rights reserved.</p>"
    )
    assert extract.is_front_matter(soup) is True


def test_is_front_matter_copyright_via_library_of_congress():
    soup = _soup(
        "<p>Copyright 2018</p>"
        "<p>Library of Congress Cataloging-in-Publication Data</p>"
    )
    assert extract.is_front_matter(soup) is True


def test_is_front_matter_toc_page():
    links = "".join(f'<p><a href="#c{i}">Chapter {i}</a></p>' for i in range(10))
    soup = _soup(links)
    assert extract.is_front_matter(soup) is True


def test_is_front_matter_normal_body_false():
    soup = _soup("<h1>Chapter One</h1><p>A long paragraph about dopamine and how it works.</p>")
    assert extract.is_front_matter(soup) is False


def test_is_front_matter_copyright_word_alone_false():
    soup = _soup("<p>This chapter discusses copyright law in detail.</p>")
    assert extract.is_front_matter(soup) is False


def test_is_front_matter_long_content_with_copyright_false():
    # 长篇正文（含每篇版权行 Copyright ©）不应判为前置页整篇跳过
    soup = _soup(
        "<h1>Essay</h1>"
        + "<p>" + "word " * 200 + " Copyright © 2024 Author. All rights reserved.</p>"
        + "<p>" + "more text " * 200 + "</p>"
    )
    assert extract.is_front_matter(soup) is False


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
