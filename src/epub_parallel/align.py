"""英文块后插中文兄弟节点（幂等）。"""

CN_CLASS = "cn-parallel"

# 这些容器内的翻译要作为子节点追加，而非同级兄弟
_CONTAINER_TAGS = {"li", "td", "th"}


def _class_list(tag):
    """统一 class 取值：HTML 解析器返回 list，XML 解析器返回字符串。"""
    classes = tag.get("class")
    if classes is None:
        return []
    if isinstance(classes, str):
        return classes.split()
    return list(classes)


def _is_cn_parallel(tag):
    if tag is None or getattr(tag, "name", None) is None:
        return False
    return CN_CLASS in _class_list(tag)


def _already_has_translation(block, in_container):
    if in_container:
        return any(_is_cn_parallel(c) for c in block.children)
    return _is_cn_parallel(block.find_next_sibling())


def is_translated(block):
    """块是否已有中文译文（其后紧跟 cn-parallel 兄弟，或容器内已有）。"""
    in_container = block.name in _CONTAINER_TAGS
    return _already_has_translation(block, in_container)


def insert_translation(block, cn_text):
    """在英文块后插入 `<p class="cn-parallel">译文</p>`，幂等返回新标签（已存在则返回 None）。"""
    in_container = block.name in _CONTAINER_TAGS
    if _already_has_translation(block, in_container):
        return None

    new = block.new_tag("p")
    new["class"] = [CN_CLASS]
    new.string = cn_text

    if in_container:
        block.append(new)
    else:
        block.insert_after(new)
    return new
