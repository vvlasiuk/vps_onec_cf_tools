"""
CLI інструменту onec_ctx.

Команди:
    inspect <file.cf>            — показати структуру контейнера .cf (діагностика)
    process <dump_dir> <out_dir> — обійти дерево вивантаження й побудувати артефакт
                                   (кістяки + винесені тіла + індекс визначень)

`process` — основний конвеєр. Вхід — каталог "Выгрузить конфигурацию в файлы".
Реконструкція назад не підтримується; вихід — тільки для читання.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from onec_ctx.cf.unpack import walk_container, format_tree, summarize
from onec_ctx.inventory import walk_tree, build_symbol_index


def cmd_inspect(args: argparse.Namespace) -> int:
    with open(args.cf, "rb") as f:
        nodes = walk_container(f, max_depth=args.max_depth)
    print(format_tree(nodes))
    print("\n--- підсумок ---")
    for k, v in summarize(nodes).items():
        print(f"{k}: {v}")
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    from onec_ctx.manifest import build_manifest
    entries = walk_tree(args.dump_dir)
    stats = build_manifest(
        entries, args.out_db,
        source_tree=args.dump_dir,
        inline_threshold=args.inline_threshold)
    print("--- підсумок ---")
    for k, v in stats.items():
        print(f"{k}: {v}")
    print(f"\nМаніфест: {args.out_db}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="onec_ctx",
        description="Підготовка контексту з конфігурації 1С")
    sub = p.add_subparsers(dest="command", required=True)

    insp = sub.add_parser("inspect", help="Показати структуру .cf")
    insp.add_argument("cf")
    insp.add_argument("--max-depth", type=int, default=32)
    insp.set_defaults(func=cmd_inspect)

    proc = sub.add_parser("process", help="Побудувати SQLite-маніфест з дерева вивантаження")
    proc.add_argument("dump_dir", help="Каталог 'Выгрузить конфигурацию в файлы'")
    proc.add_argument("out_db", help="Шлях до вихідного файла manifest.sqlite")
    proc.add_argument("--inline-threshold", type=int, default=3,
                      help="Макс. значущих рядків тіла, що лишається інлайн")
    proc.set_defaults(func=cmd_process)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
