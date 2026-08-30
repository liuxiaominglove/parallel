from bs4 import BeautifulSoup

from epub_parallel import align


def _soup(html):
    return BeautifulSoup(html, "html.parser")


def _tag(soup, name):
    return soup.find(name)


def test_insert_sibling_after_paragraph():
    soup = _soup("<p>Hello.</p>")
    p = _tag(soup, "p")
    align.insert_translation(p, "你好。")
    assert str(soup) == '<p>Hello.</p><p class="cn-parallel">你好。</p>'


def test_insert_sibling_after_heading():
    soup = _soup("<h1>Title</h1>")
    h = _tag(soup, "h1")
    align.insert_translation(h, "标题")
    assert str(soup) == '<h1>Title</h1><p class="cn-parallel">标题</p>'


def test_insert_inside_li():
    soup = _soup("<ul><li>Item one</li></ul>")
    li = _tag(soup, "li")
    align.insert_translation(li, "第一项")
    assert str(soup) == '<ul><li>Item one<p class="cn-parallel">第一项</p></li></ul>'


def test_insert_inside_table_cell():
    soup = _soup("<table><tr><td>Cell</td></tr></table>")
    td = _tag(soup, "td")
    align.insert_translation(td, "单元格")
    assert str(soup) == '<table><tr><td>Cell<p class="cn-parallel">单元格</p></td></tr></table>'


def test_idempotent_sibling_no_duplicate():
    soup = _soup("<p>Hello.</p>")
    p = _tag(soup, "p")
    align.insert_translation(p, "你好。")
    align.insert_translation(p, "你好。")
    assert str(soup).count('class="cn-parallel"') == 1


def test_idempotent_container_no_duplicate():
    soup = _soup("<ul><li>Item one</li></ul>")
    li = _tag(soup, "li")
    align.insert_translation(li, "第一项")
    align.insert_translation(li, "第一项")
    assert str(soup).count('class="cn-parallel"') == 1


def test_preserves_existing_inline_markup_in_source_block():
    soup = _soup("<p>Hello <em>world</em>.</p>")
    p = _tag(soup, "p")
    align.insert_translation(p, "你好，世界。")
    assert '<em>world</em>' in str(soup)


def test_idempotent_under_xml_parser():
    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p>Hello world.</p><p>Second.</p>'
        '</body></html>'
    )
    soup = BeautifulSoup(xhtml, "xml")
    p = soup.find("p")
    align.insert_translation(p, "你好。")
    assert str(soup).count('class="cn-parallel"') == 1
    align.insert_translation(p, "你好。")
    assert str(soup).count('class="cn-parallel"') == 1


def test_xml_parser_serializes_class_as_attribute():
    xhtml = '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body><p>Hi</p></body></html>'
    soup = BeautifulSoup(xhtml, "xml")
    p = soup.find("p")
    align.insert_translation(p, "你好。")
    assert 'class="cn-parallel"' in str(soup)


def test_is_translated_false_then_true():
    soup = _soup("<p>Hello.</p>")
    p = _tag(soup, "p")
    assert align.is_translated(p) is False
    align.insert_translation(p, "你好。")
    assert align.is_translated(p) is True


def test_is_translated_for_container_li():
    soup = _soup("<ul><li>Item</li></ul>")
    li = _tag(soup, "li")
    assert align.is_translated(li) is False
    align.insert_translation(li, "项")
    assert align.is_translated(li) is True
