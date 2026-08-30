# ADR 0001 — 双语 EPUB 的排版、引擎与读写方案

状态：提议

## 决策

### 本质

三项互相独立的选型，均为可逆决策（可重跑、可替换）：
1. 排版：段落交错（每段英文后紧跟一段中文）。
2. 翻译引擎：DeepSeek（`deepseek-chat`）。
3. EPUB 读写：zipfile 直改 XHTML（不用 ebooklib 回写）。

### 最佳实践

1. **排版**：Kindle 不支持双栏、句子级对齐易错、章节级对照无可读性；段落交错是兼容性与实现成本的最优解。Apple Books / 微信读书 / 浏览器 / Calibre 全通吃。
2. **引擎**：DeepSeek 便宜、中英翻译质量好、OpenAI 兼容接口 + `response_format=json_object` 输出稳定（已实测），日后可无缝切换其他兼容引擎。
3. **读写**：ebooklib 是"从零造书"的好工具，但 round-trip 会崩溃/丢信息（实测：`set_cover` 生成空 body 的 `cover.xhtml` 导致 nav 生成崩溃；读回后 toc 项 `uid=None` 导致 NCX 生成崩溃）。zipfile 直改 XHTML 只动文本、其余文件字节原样保留，是处理"已有 EPUB"最稳的方式。

### 方案

1. 段落交错：英文 `<p>` 后插 `<p class="cn-parallel">译文</p>`，英文 DOM 原封不动（内联标签/图片/链接全保留）。`<li>/<td>/<th>` 的译文作为容器子节点追加。
2. DeepSeek：`deepseek-v4-flash`（原 `deepseek-chat` 别名已弃用），base_url `https://api.deepseek.com`，key 读 `DEEPSEEK_API_KEY`；抽象成通用 OpenAI 兼容客户端（`--model/--base-url/--api-key` 可覆盖）。默认 `thinking: {"type": "disabled"}` 关闭推理模式——v4 是推理模型，不关会为翻译浪费大量 reasoning token（实测 2 块从 287 completion token 降到 18）。
3. 读写：`zipfile` 读 `container.xml → OPF → manifest/spine`，解析 spine 内的 XHTML 文档（过滤 `properties="nav"` 的导航文档），BeautifulSoup（XML 解析器，失败退回 HTML）改完序列化为 UTF-8；写出时 `mimetype` 首位 + 无压缩存储，其余条目原样复制。

## 后果

- 优点：输出保真（封面/目录/元数据/图片字节不变）、断点续跑（checkpoint JSON）、成本极低、单次运行预算上限（`--max-cost`）+ 事前预估门槛。
- 边界：仅处理 `p/h1-h6/li/blockquote/dt/dd/figcaption/td/th/caption` 叶级块，代码/表格内嵌/诗歌等复杂结构原样保留不译。
- 成本模型：单价可配置（默认 v4-flash 美元价），跑前按剩余块粗估、跑中按 API `usage` 真实 token 硬停。
- 内容分级：按 EPUB3 `epub:type`（顶层 section/div）识别并跳过 index/copyright-page/titlepage/dedication/colophon/cover 等前后置页（`part` 保留）；内容级幂等靠 `cn-parallel` 标记，重跑不重复翻译。
