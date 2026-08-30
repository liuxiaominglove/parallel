"""EPUB 读写：用 zipfile 直改 XHTML，其余文件字节原样保留。"""

import os
import posixpath
import xml.etree.ElementTree as ET
import zipfile

from bs4 import BeautifulSoup

CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF_NS = "http://www.idpf.org/2007/opf"
XHTML_TYPES = {"application/xhtml+xml", "text/html"}


class EpubError(Exception):
    pass


def resolve_href(opf_path, href):
    """把 manifest/spine 里的相对 href 解析为 zip 内完整路径（去 fragment）。"""
    href = href.split("#", 1)[0]
    opf_dir = posixpath.dirname(opf_path)
    return posixpath.normpath(posixpath.join(opf_dir, href))


def parse_xhtml(data):
    """解析 XHTML 字节；优先 XML 解析（保留命名空间/自闭合），失败退回 HTML。"""
    try:
        return BeautifulSoup(data, "xml")
    except Exception:
        return BeautifulSoup(data, "html.parser")


def serialize_xhtml(soup):
    """序列化为 UTF-8 字节（XML 解析时保留声明与命名空间）。"""
    return soup.encode("utf-8")


def _extract_doc_types(soup):
    """取 body 直接子元素的 epub:type 与 data-type 值（文档级语义标记）。"""
    types = set()
    body = soup.find("body")
    container = body if body is not None else soup
    for child in container.find_all(True, recursive=False):
        for attr in ("epub:type", "data-type"):
            value = child.get(attr)
            if value:
                types.update(value.split())
    return types


class Epub:
    def __init__(self, path):
        self.path = str(path)
        self.opf_path = None
        self.opf_dir = None
        self._spine = []  # [(href, media_type)]
        self._nav_hrefs = set()
        self._doc_bytes = {}
        self._doc_types = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            raise EpubError(f"文件不存在: {self.path}")
        try:
            with zipfile.ZipFile(self.path) as z:
                container = z.read("META-INF/container.xml")
                self.opf_path = self._find_opf_path(container)
                self.opf_dir = posixpath.dirname(self.opf_path)
                self._parse_opf(z.read(self.opf_path))
                for href, media_type in self._spine:
                    if media_type in XHTML_TYPES and href not in self._nav_hrefs:
                        self._doc_bytes[href] = z.read(href)
        except zipfile.BadZipFile as e:
            raise EpubError(f"不是有效的 EPUB（zip）: {self.path}") from e
        except KeyError as e:
            raise EpubError(f"EPUB 结构异常，缺少条目: {e}") from e

    @staticmethod
    def _find_opf_path(container_bytes):
        try:
            root = ET.fromstring(container_bytes)
            rootfile = root.find(f".//{{{CONTAINER_NS}}}rootfile")
            return rootfile.get("full-path")
        except ET.ParseError as e:
            raise EpubError("META-INF/container.xml 解析失败") from e

    def _parse_opf(self, opf_bytes):
        root = ET.fromstring(opf_bytes)
        manifest = {}
        for item in root.findall(f".//{{{OPF_NS}}}item"):
            item_id = item.get("id")
            href = item.get("href")
            media_type = item.get("media-type")
            properties = item.get("properties") or ""
            manifest[item_id] = (href, media_type)
            if "nav" in properties.split():
                self._nav_hrefs.add(resolve_href(self.opf_path, href))
        spine = [item.get("idref") for item in root.findall(f".//{{{OPF_NS}}}itemref")]
        self._spine = [
            (resolve_href(self.opf_path, manifest[idref][0]), manifest[idref][1])
            for idref in spine
            if idref in manifest
        ]

    def documents(self):
        """返回按 spine 顺序的 XHTML 文档路径列表（不含导航文档）。"""
        return [
            href
            for href, media_type in self._spine
            if media_type in XHTML_TYPES and href not in self._nav_hrefs
        ]

    def document_bytes(self, href):
        return self._doc_bytes[href]

    def document_soup(self, href):
        return parse_xhtml(self._doc_bytes[href])

    def document_types(self, href):
        """返回文档的语义类型集合（顶层 section/div 的 epub:type 与 data-type），缓存。"""
        if href not in self._doc_types:
            self._doc_types[href] = _extract_doc_types(self.document_soup(href))
        return self._doc_types[href]

    def write(self, output_path, modified):
        """把输入 zip 整体复制到输出，替换 modified 中的文档字节。"""
        modified = {posixpath.normpath(k): v for k, v in modified.items()}
        with zipfile.ZipFile(self.path) as zin, zipfile.ZipFile(
            output_path, "w", zipfile.ZIP_DEFLATED
        ) as zout:
            names = zin.namelist()
            if "mimetype" in names:
                zout.writestr(
                    zipfile.ZipInfo("mimetype"),
                    zin.read("mimetype"),
                    compress_type=zipfile.ZIP_STORED,
                )
            for name in names:
                if name == "mimetype":
                    continue
                if name in modified:
                    zout.writestr(name, modified[name])
                else:
                    zout.writestr(name, zin.read(name))
