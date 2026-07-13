"""
Розпакування та інспекція контейнера конфігурації 1С (.cf).

Крок 1 конвеєра. Мета — відкрити контейнер, рекурсивно розгорнути вкладені
контейнери, зробити inflate стиснутих записів і побудувати читабельну мапу
внутрішньої структури.

На цьому кроці ми свідомо НЕ інтерпретуємо метадані (GUID -> тип об'єкта ->
людський шлях). Спершу треба побачити реальну будову конкретної конфігурації —
на її основі проектується декодер метаданих (крок 2).

Контейнерний рівень читається бібліотекою onec_dtools. "Своя" робота проекту
починається вище — на рівні метаданих, у наступних кроках.
"""
from __future__ import annotations

import io
import os
import zlib
from dataclasses import dataclass, field

from onec_dtools.container_reader import ContainerReader

# Магія початку контейнера 1С (перші 4 байти).
CONTAINER_MAGIC = b"\xFF\xFF\xFF\x7F"


@dataclass
class Node:
    """Вузол внутрішнього дерева контейнера."""
    name: str
    size: int              # розмір даних після можливого inflate
    is_container: bool
    inflated: bool         # чи були дані deflate-стиснуті
    children: list["Node"] = field(default_factory=list)


def _read_entry_bytes(entry) -> bytes:
    """Зчитує всі чанки запису контейнера в один bytes."""
    return b"".join(entry.data)


def _maybe_inflate(raw: bytes) -> tuple[bytes, bool]:
    """
    Пробує розпакувати raw deflate (у контейнері 1С немає zlib-заголовка,
    тому wbits=-15). Якщо дані не стиснуті — повертає їх без змін.
    Повертає (дані, чи_було_розпаковано).
    """
    if not raw:
        return raw, False
    try:
        data = zlib.decompressobj(-15).decompress(raw)
        # порожній результат при непорожньому вході трактуємо як "не deflate"
        if not data:
            return raw, False
        return data, True
    except zlib.error:
        return raw, False


def _looks_like_container(data: bytes) -> bool:
    return data[:4] == CONTAINER_MAGIC


def walk_container(file_obj, depth: int = 0, max_depth: int = 32) -> list[Node]:
    """
    Рекурсивно обходить контейнер, повертає список вузлів верхнього рівня.

    file_obj — відкритий бінарний файл або io.BytesIO з контейнером.
    Один битий вузол не валить увесь обхід: помилка фіксується в імені вузла.
    """
    reader = ContainerReader(file_obj)
    nodes: list[Node] = []

    for name, entry in reader.entries.items():
        raw = _read_entry_bytes(entry)
        data, inflated = _maybe_inflate(raw)
        is_container = _looks_like_container(data)

        node = Node(name=name, size=len(data), is_container=is_container, inflated=inflated)

        if is_container and depth < max_depth:
            try:
                node.children = walk_container(io.BytesIO(data), depth + 1, max_depth)
            except Exception as exc:  # noqa: BLE001 — навмисно широко, щоб не впасти на одному вузлі
                node.name += f"  [!! не вдалося розгорнути: {exc}]"

        nodes.append(node)

    return nodes


def format_tree(nodes: list[Node], indent: int = 0) -> str:
    """Читабельне текстове представлення дерева."""
    lines: list[str] = []
    for n in nodes:
        flags = []
        if n.is_container:
            flags.append("container")
        if n.inflated:
            flags.append("deflate")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        lines.append(f"{'  ' * indent}{n.name}  ({n.size} B){flag_str}")
        if n.children:
            lines.append(format_tree(n.children, indent + 1))
    return "\n".join(lines)


def summarize(nodes: list[Node]) -> dict:
    """Підсумок: кількість записів, з них контейнерів, максимальна глибина."""
    total = 0
    containers = 0
    max_depth = 0

    def _rec(ns: list[Node], depth: int) -> None:
        nonlocal total, containers, max_depth
        if ns:
            max_depth = max(max_depth, depth)
        for n in ns:
            total += 1
            if n.is_container:
                containers += 1
            _rec(n.children, depth + 1)

    _rec(nodes, 1)
    return {"entries": total, "containers": containers, "max_depth": max_depth}


def dump_container(file_obj, out_dir: str, depth: int = 0, max_depth: int = 32) -> None:
    """
    Розпаковує контейнер у каталог, зберігаючи вкладеність, для ручного перегляду.

    Імена — службові (GUID тощо): інтерпретації метаданих на цьому кроці ще немає.
    Вкладені контейнери стають підкаталогами із суфіксом ".dir".
    """
    os.makedirs(out_dir, exist_ok=True)
    reader = ContainerReader(file_obj)

    for name, entry in reader.entries.items():
        raw = _read_entry_bytes(entry)
        data, _ = _maybe_inflate(raw)
        safe = name.replace("/", "_").replace("\\", "_") or "_unnamed"

        if _looks_like_container(data) and depth < max_depth:
            sub = os.path.join(out_dir, safe + ".dir")
            try:
                dump_container(io.BytesIO(data), sub, depth + 1, max_depth)
                continue
            except Exception:  # noqa: BLE001 — якщо не контейнер за фактом, пишемо як файл
                pass

        with open(os.path.join(out_dir, safe), "wb") as fh:
            fh.write(data)
