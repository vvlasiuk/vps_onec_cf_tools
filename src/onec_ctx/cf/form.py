"""
Витяг тексту модуля зі звичайної форми 1С (Form.bin).

Звичайна (некерована) форма при штатному вивантаженні лягає в бінарний
контейнер Form.bin, а не в текстовий Module.bsl. Усередині контейнера два
записи: 'form' (розмітка елементів) і 'module' (код). Нам потрібен 'module'.

Цей витяг свідомо зроблений власним кодом (onec_dtools + відкат inflate),
бо v8unpack 1.2.6 на цих контейнерах падає: він безумовно розпаковує кожен
запис як deflate і не має відкату на нестиснуті записи.
"""
from __future__ import annotations

import io
import zlib

from onec_dtools.container_reader import ContainerReader

MODULE_ENTRY = "module"


def _read_entry_bytes(entry) -> bytes:
    return b"".join(entry.data)


def _maybe_inflate(raw: bytes) -> bytes:
    """Розпаковує raw deflate; якщо не стиснуто — повертає як є."""
    if not raw:
        return raw
    try:
        data = zlib.decompressobj(-15).decompress(raw)
        return data if data else raw
    except zlib.error:
        return raw


def extract_form_module(form_bin: bytes) -> str | None:
    """
    Повертає текст модуля форми (str) або None, якщо запису 'module' немає
    (форма без коду) чи контейнер не читається.

    form_bin — вміст файла Form.bin (bytes).
    """
    try:
        reader = ContainerReader(io.BytesIO(form_bin))
    except Exception:
        return None

    entry = reader.entries.get(MODULE_ENTRY)
    if entry is None:
        return None

    data = _maybe_inflate(_read_entry_bytes(entry))
    if not data:
        return None

    # тексти модулів 1С — UTF-8 (часто з BOM); підстрахуємось відкатом
    for enc in ("utf-8-sig", "utf-8", "utf-16-le", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_form_module_file(path: str) -> str | None:
    """Зручний обгортка: приймає шлях до Form.bin на диску."""
    with open(path, "rb") as fh:
        return extract_form_module(fh.read())
