# parallel — EPUB 中英双语对照转换

## 项目说明

把英文 EPUB 转成中英段落交错的双语 EPUB（每段英文后紧跟一段中文 `.cn-parallel`）。
翻译引擎 DeepSeek（`deepseek-chat`），key 读环境变量 `DEEPSEEK_API_KEY`。

## 技术栈

- Python 3.13 + pytest（TDD）
- `beautifulsoup4` 解析/改写 XHTML，`requests` 调 DeepSeek
- **EPUB 读写用 zipfile 直改 XHTML**（不用 ebooklib 回写——ebooklib round-trip 会丢 cover/toc/uid，见 docs/adr）

## TDD 纪律

严格 RED → GREEN → REFACTOR。业务逻辑、工具函数、边界情况必须写测试。

### 测试命令

```bash
.venv/bin/pytest            # 跑全部测试
.venv/bin/pytest -q         # 精简输出
.venv/bin/pytest tests/test_extract.py   # 单文件
```

### 测试文件位置

`foo.test.py` 放 `tests/` 目录，命名 `test_<module>.py`。

### Mock 规则

只 mock 外部边界（网络请求/文件系统），不 mock 自己的业务逻辑。

## 目录结构

```
src/epub_parallel/
  cli.py         # argparse 入口
  config.py      # env/flag 加载
  epub_io.py     # zipfile 读写 EPUB
  extract.py     # XHTML -> 有序可译块
  translate.py   # DeepSeek 客户端（批处理+重试+校验）
  align.py       # 英文块后插中文兄弟节点
  checkpoint.py  # 断点续跑（翻译缓存）
tests/
docs/adr/
```

## 常用命令

```bash
.venv/bin/python -m epub_parallel <输入.epub>                  # 输出 <原名>.bilingual.epub
.venv/bin/python -m epub_parallel <输入.epub> -o out.epub
.venv/bin/python -m epub_parallel <输入.epub> --dry-run        # 只统计，不调 API
.venv/bin/python -m epub_parallel <输入.epub> --max-blocks 20  # 限量试跑
```
