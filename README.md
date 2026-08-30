# parallel — EPUB 中英双语对照转换

把英文 EPUB 转成中英段落交错的双语 EPUB：每段英文后紧跟一段中文译文（`.cn-parallel`），英文原文、封面、目录、图片、排版原样保留。

## 环境

- Python 3.13（>=3.10）
- 翻译引擎 DeepSeek（`deepseek-v4-flash`），key 读环境变量 `DEEPSEEK_API_KEY`

## 安装

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
export DEEPSEEK_API_KEY=sk-...   # 你的 key
```

## 使用

```bash
# 直接转换，输出 <原名>.bilingual.epub（同目录）
.venv/bin/python -m epub_parallel <输入.epub>

# 指定输出路径
.venv/bin/python -m epub_parallel <输入.epub> -o out.epub

# 只统计可译块数 / 预估，不调 API
.venv/bin/python -m epub_parallel <输入.epub> --dry-run

# 限量试跑（只翻译前 20 块）
.venv/bin/python -m epub_parallel <输入.epub> --max-blocks 20

# 切换引擎（任意 OpenAI 兼容接口）
.venv/bin/python -m epub_parallel in.epub --base-url https://api.moonshot.cn/v1 --model moonshot-v1-8k --thinking

# 成本上限：单次运行最多花 $1（美元）
.venv/bin/python -m epub_parallel in.epub --max-cost 1.0

# 预估超限仍继续（跳过事前门槛）
.venv/bin/python -m epub_parallel in.epub --max-cost 1.0 --yes

# 跳过指定类型的前后置页（默认已跳过 index/copyright-page/titlepage/dedication/colophon/cover）
.venv/bin/python -m epub_parallel in.epub --skip-types index,copyright-page
```

> 日后你只需把 EPUB 文件地址发我，我按上述命令直接跑，输出 `<原名>.bilingual.epub`。

## 成本控制

- 跑前打印预估（按**剩余未译块**估算 token 与美元成本），`--dry-run` 也显示。
- `--max-cost` 设单次运行预算上限：预估超限且无 `--yes` → 中止不调 API；跑中累计真实 token 达到上限 → 停止并**写出已译部分**。
- 单价默认 `deepseek-v4-flash` 现价 **$0.14/M 输入 / $0.28/M 输出**，可用 `--input-price` / `--output-price` 覆盖（单位：美元）。
- 默认**关闭推理模式**（`thinking: disabled`）省输出 token；`--thinking` 可开启。

## 配置文件（可选）

默认读 `~/.config/epub-parallel/config.json`（可用 `--config` 覆盖路径）。优先级：**CLI flag > 配置文件 > 代码默认**。api_key 不走文件，只读环境变量。

```json
{ "max_cost": 1.0 }
```

常用字段：`max_cost`（每次运行默认美元上限，防误跑超长书）、`model`、`base_url`、`input_price`、`output_price`、`batch_size`、`disable_thinking`。

## 断点续跑

翻译结果缓存在 `<原名>.checkpoint.json`。中途中断或达到 `--max-cost` 后，**重跑同一命令**即可继续——已译段落自动跳过、不重复翻译、不重复计费。续跑时调大或去掉 `--max-cost`。翻译过程实时显示进度（`[done/total] 已花 $cost`），失败时会提示已翻译块数与续跑方式。

## 设计要点

- 只处理 `p / h1~h6 / li / blockquote / dt / dd / figcaption / td / th / caption` 的叶级块；代码、脚本、空段、纯数字、纯中文块跳过。
- **跳过前后置页**：按 EPUB3 语义标记 `epub:type`（顶层 section/div）识别并跳过索引、版权页、扉页、致谢、版权说明、封面等元内容（默认类型可配 `--skip-types`）；`part`（卷标题页）保留。
- **内容级幂等**：识别已有 `cn-parallel` 兄弟的块，重跑/换机器不重复翻译。
- 批处理翻译 + 指数退避重试 + JSON 补逗号兜底 + 译文条数校验。
- EPUB 读写用 zipfile 直改 XHTML，其余文件字节原样保留（见 docs/adr）。

## 测试

```bash
.venv/bin/pytest          # 全部测试
.venv/bin/pytest -q
.venv/bin/pytest tests/test_translate.py
```

## 目录结构

```
src/epub_parallel/
  cli.py         # argparse 入口
  config.py      # env/flag 加载
  epub_io.py     # zipfile 读写 EPUB
  extract.py     # XHTML -> 有序可译块
  translate.py   # DeepSeek 客户端（批处理+重试+校验）
  align.py       # 英文块后插中文兄弟节点
  pipeline.py    # 编排：提取->翻译->插入->写出
  checkpoint.py  # 断点续跑（翻译缓存）
```
