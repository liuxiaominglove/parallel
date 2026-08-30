"""命令行入口。"""

import argparse
import sys
from pathlib import Path

from epub_parallel import epub_io, pipeline, translate
from epub_parallel.checkpoint import Checkpoint, CheckpointError
from epub_parallel.config import Config, ConfigError
from epub_parallel.translate import TranslateError


def default_output_path(input_path):
    p = Path(input_path)
    return str(p.with_name(p.stem + ".bilingual.epub"))


def default_checkpoint_path(input_path):
    p = Path(input_path)
    return str(p.with_name(p.stem + ".checkpoint.json"))


def build_parser():
    p = argparse.ArgumentParser(
        prog="epub-parallel",
        description="把英文 EPUB 转成中英段落交错的双语 EPUB（DeepSeek 翻译）。",
    )
    p.add_argument("input", help="输入 EPUB 路径")
    p.add_argument("-o", "--output", help="输出 EPUB 路径（默认 <原名>.bilingual.epub）")
    p.add_argument("--dry-run", action="store_true", help="只统计可译块数，不调用 API")
    p.add_argument("--max-blocks", type=int, help="最多翻译的块数（限量试跑）")
    p.add_argument("--model", help="模型名（默认 deepseek-v4-flash）")
    p.add_argument("--base-url", help="API base URL（默认 https://api.deepseek.com）")
    p.add_argument("--api-key", help="API key（默认读环境变量 DEEPSEEK_API_KEY）")
    p.add_argument("--batch-size", type=int, help="每批翻译块数（默认 20）")
    p.add_argument("--checkpoint", help="断点文件路径（默认 <原名>.checkpoint.json）")
    p.add_argument("--max-cost", type=float, help="单次运行预算上限（美元），超过则停止")
    p.add_argument("--input-price", type=float, help="每百万输入 token 单价（默认 0.14 美元）")
    p.add_argument("--output-price", type=float, help="每百万输出 token 单价（默认 0.28 美元）")
    p.add_argument("--yes", action="store_true", help="预估超限时仍继续")
    p.add_argument("--thinking", action="store_true", help="启用推理模式（默认关闭，省 token）")
    p.add_argument("--config", help="配置文件路径（默认 ~/.config/epub-parallel/config.json）")
    p.add_argument(
        "--skip-types",
        help="跳过的文档类型（epub:type），逗号分隔。默认 index,copyright-page,titlepage,dedication,colophon,cover",
    )
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    skip_types = (
        tuple(t.strip() for t in args.skip_types.split(",") if t.strip())
        if args.skip_types
        else None
    )
    try:
        config = Config.from_env(
            config_path=args.config,
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            batch_size=args.batch_size,
            max_cost=args.max_cost,
            input_price=args.input_price,
            output_price=args.output_price,
            disable_thinking=not args.thinking,
            skip_types=skip_types,
        )
    except ConfigError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    try:
        epub = epub_io.Epub(args.input)
    except epub_io.EpubError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    checkpoint_path = args.checkpoint or default_checkpoint_path(args.input)
    try:
        checkpoint = Checkpoint(checkpoint_path)
    except CheckpointError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    docs = epub.documents()
    translatable = pipeline.translatable_documents(epub, config.skip_types)
    skipped = len(docs) - len(translatable)
    counts = pipeline.count_blocks(epub, skip_types=config.skip_types)
    total = sum(counts.values())
    remaining = pipeline.remaining_texts(epub, checkpoint, skip_types=config.skip_types)
    done = total - len(remaining)
    print(f"文档: 共 {len(docs)}，跳过 {skipped} 个（前后置页），可译 {len(translatable)}")
    print(f"可译块总数: {total}（已译 {done}，剩余 {len(remaining)}）")
    for href, n in counts.items():
        print(f"  {n:>6}  {href}")

    in_tokens, out_tokens, est_cost = pipeline.estimate_cost(
        remaining, config.input_price, config.output_price
    )
    print(
        f"预估剩余成本: 输入 ~{in_tokens:.0f} token / 输出 ~{out_tokens:.0f} token"
        f" / 约 ${est_cost:.6f}"
    )

    if args.dry_run:
        print("dry-run：未调用翻译 API。")
        return 0

    output_path = args.output or default_output_path(args.input)

    if total == 0:
        print("没有可翻译的内容。", file=sys.stderr)
        return 1

    if config.max_cost is not None and est_cost > config.max_cost and not args.yes:
        print(
            f"预估成本 ${est_cost:.6f} 超过上限 ${config.max_cost:.6f}，已中止。"
            f"加 --yes 继续，或调大 --max-cost。",
            file=sys.stderr,
        )
        return 1

    try:
        translator = translate.Translator(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            temperature=config.temperature,
            timeout=config.timeout,
            max_retries=config.max_retries,
            disable_thinking=config.disable_thinking,
        )

        def _progress(done, total, cost):
            print(f"\r进度: [{done}/{total}] 已花 ${cost:.6f}", end="", flush=True)

        new_count, reason = pipeline.translate_all(
            epub, checkpoint, translator, config,
            max_blocks=args.max_blocks, on_progress=_progress,
        )
        if total > 0:
            print()
        pipeline.build_output(epub, checkpoint, output_path, skip_types=config.skip_types)
    except (TranslateError, CheckpointError) as e:
        print(f"错误: {e}", file=sys.stderr)
        done = pipeline.count_translated(epub, checkpoint, config.skip_types)
        print(f"已翻译 {done} 块并保存，重跑同一命令即可续跑。", file=sys.stderr)
        return 1

    print(f"本次新增翻译块: {new_count}")
    print(
        f"成本对比: 预估 ~${est_cost:.6f} / 实际 ~${translator.cost(config.input_price, config.output_price):.6f}"
    )
    print(f"已写出: {output_path}")
    if reason == "max_cost":
        print("已达单次预算上限，已写出已译部分。续跑：调大 --max-cost 或去掉后重跑同一命令。")
    elif reason == "max_blocks":
        print("已达 --max-blocks 上限。续跑：去掉 --max-blocks 或调大后重跑。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
