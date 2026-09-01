import zipfile

import pytest

from epub_parallel.epub_io import Epub, EpubError, parse_xhtml, resolve_href, serialize_xhtml


def test_read_spine_order(epub_path):
    epub = Epub(str(epub_path))
    docs = epub.documents()
    assert [d.split("/")[-1] for d in docs] == ["chap_1.xhtml", "chap_2.xhtml"]


def test_document_bytes_readable(epub_path):
    epub = Epub(str(epub_path))
    for href in epub.documents():
        assert epub.document_bytes(href).startswith(b"<?xml") or b"<html" in epub.document_bytes(href)


def test_missing_file_raises(tmp_path):
    with pytest.raises(EpubError):
        Epub(str(tmp_path / "nope.epub"))


def test_resolve_href_relative_and_fragment():
    assert resolve_href("EPUB/content.opf", "chap_1.xhtml") == "EPUB/chap_1.xhtml"
    assert resolve_href("EPUB/content.opf", "text/chap_1.xhtml#p1") == "EPUB/text/chap_1.xhtml"
    assert resolve_href("EPUB/OPS/content.opf", "../text/a.xhtml") == "EPUB/text/a.xhtml"


def test_parse_serialize_roundtrip_preserves_xml():
    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p>Hello <em>world</em>.</p><p>Line<br/>break.</p>'
        '</body></html>'
    ).encode("utf-8")
    soup = parse_xhtml(xhtml)
    out = serialize_xhtml(soup)
    assert out.startswith(b'<?xml')
    assert b'<br/>' in out
    assert b'xmlns="http://www.w3.org/1999/xhtml"' in out
    # re-parseable
    soup2 = parse_xhtml(out)
    assert soup2.find("p").get_text(" ", strip=True).replace(" ", "") == "Helloworld."


def test_parse_malformed_falls_back_to_html():
    bad = b"<html><body><p>unclosed"
    soup = parse_xhtml(bad)
    assert soup.find("p") is not None


def test_write_modifies_only_target_doc_and_preserves_rest(epub_path, tmp_path):
    epub = Epub(str(epub_path))
    original_names = None
    with zipfile.ZipFile(str(epub_path)) as z:
        original_names = z.namelist()
        original_opf = z.read(epub.opf_path)
        original_container = z.read("META-INF/container.xml")

    chap1 = epub.documents()[0]
    soup = epub.document_soup(chap1)
    p = soup.find("p")
    cn = soup.new_tag("p")
    cn["class"] = ["cn-parallel"]
    cn.string = "你好。"
    p.insert_after(cn)

    out = tmp_path / "out.epub"
    epub.write(str(out), {chap1: serialize_xhtml(soup)})

    with zipfile.ZipFile(str(out)) as z:
        names = z.namelist()
        assert names == original_names
        assert names[0] == "mimetype"
        assert z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert z.read(epub.opf_path) == original_opf
        assert z.read("META-INF/container.xml") == original_container
        modified = z.read(chap1)
        assert b"cn-parallel" in modified
        # chap_2 unchanged (byte-identical)
        assert z.read(epub.documents()[1]) == epub.document_bytes(epub.documents()[1])


def test_document_soup_returns_soup(epub_path):
    epub = Epub(str(epub_path))
    soup = epub.document_soup(epub.documents()[0])
    assert soup.find("h1").get_text(strip=True) == "Chapter One"


def test_document_types_recognizes_epub_type(typed_epub_path):
    epub = Epub(str(typed_epub_path))
    docs = epub.documents()  # 顺序：chapter,index,copyright,titlepage,dedication,part,colophon,cover
    assert epub.document_types(docs[0]) == {"chapter"}
    assert epub.document_types(docs[1]) == {"index"}
    assert epub.document_types(docs[2]) == {"copyright-page"}
    assert epub.document_types(docs[5]) == {"part"}


def test_document_types_cover_falls_back_to_data_type(typed_epub_path):
    epub = Epub(str(typed_epub_path))
    cover = epub.documents()[7]
    assert epub.document_types(cover) == {"cover"}


def test_document_types_no_markers_returns_empty(epub_path):
    epub = Epub(str(epub_path))
    href = epub.documents()[0]
    assert epub.document_types(href) == set()


def test_container_missing_rootfile_raises(tmp_path):
    p = tmp_path / "bad.epub"
    with zipfile.ZipFile(str(p), "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"></container>',
        )
    with pytest.raises(EpubError):
        Epub(str(p))


def test_container_rootfile_missing_full_path_raises(tmp_path):
    p = tmp_path / "bad.epub"
    with zipfile.ZipFile(str(p), "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
            "<rootfiles><rootfile/></rootfiles></container>",
        )
    with pytest.raises(EpubError):
        Epub(str(p))


def test_malformed_opf_raises(tmp_path):
    p = tmp_path / "bad.epub"
    with zipfile.ZipFile(str(p), "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
            '<rootfiles><rootfile full-path="content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr("content.opf", "<package>unclosed")
    with pytest.raises(EpubError):
        Epub(str(p))


def test_write_in_place_does_not_corrupt(epub_path, tmp_path):
    import shutil

    target = tmp_path / "inplace.epub"
    shutil.copyfile(str(epub_path), str(target))

    epub = Epub(str(target))
    chap1 = epub.documents()[0]
    soup = epub.document_soup(chap1)
    p = soup.find("p")
    cn = soup.new_tag("p")
    cn["class"] = ["cn-parallel"]
    cn.string = "你好。"
    p.insert_after(cn)

    epub.write(str(target), {chap1: serialize_xhtml(soup)})

    # 输出路径 == 输入路径：源文件不能被截断损坏，且译文已写入
    epub2 = Epub(str(target))
    assert b"cn-parallel" in epub2.document_bytes(epub2.documents()[0])


def test_write_accepts_pathlib_path(epub_path, tmp_path):
    import shutil
    from pathlib import Path

    target = tmp_path / "pathobj.epub"
    shutil.copyfile(str(epub_path), str(target))

    epub = Epub(str(target))
    chap1 = epub.documents()[0]
    soup = epub.document_soup(chap1)
    p = soup.find("p")
    cn = soup.new_tag("p")
    cn["class"] = ["cn-parallel"]
    cn.string = "你好。"
    p.insert_after(cn)

    out = tmp_path / "out.epub"
    epub.write(out, {chap1: serialize_xhtml(soup)})  # 传 Path 对象而非 str

    assert out.exists()
    epub2 = Epub(str(out))
    assert b"cn-parallel" in epub2.document_bytes(epub2.documents()[0])
