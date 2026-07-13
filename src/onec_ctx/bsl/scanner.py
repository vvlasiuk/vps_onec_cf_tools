"""
Сканер BSL: класифікує рядки модуля так, щоб надійно знаходити межі
процедур/функцій. Головна мета — не сплутати ключові слова, що стоять
всередині рядкових літералів або коментарів, зі справжніми конструкціями.

Це не повний парсер мови, а свідомо вузький лексер під одну задачу:
визначити, де починається й закінчується кожна процедура/функція, і
відокремити «скелетні» рядки (директиви, сигнатури, Перем, регіони,
доккоментарі) від тіла.

Особливості BSL, які враховано:
- рядкові літерали в лапках "...", з подвоєнням "" всередині;
- багаторядкові рядки з продовженням через | на початку наступного рядка;
- коментарі // до кінця рядка;
- директиви компіляції &НаКлиенте/&НаСервере/... перед оголошенням;
- препроцесор #Если/#Тогда/#Иначе/#КонецЕсли та #Область/#КонецОбласти;
- регістронезалежність ключових слів; підтримка рос./укр. написань.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class LineKind(Enum):
    PROC_START = "proc_start"      # Процедура/Функция ...
    PROC_END = "proc_end"         # КонецПроцедуры/КонецФункции
    DIRECTIVE = "directive"        # &НаКлиенте тощо
    VAR = "var"                    # Перем ...
    REGION = "region"              # #Область / #КонецОбласти
    PREPROC = "preproc"            # #Если / #Тогда / #Иначе / #КонецЕсли
    DOC_COMMENT = "doc_comment"    # // коментар (рядок цілком коментар)
    BLANK = "blank"
    CODE = "code"                  # звичайний рядок тіла


# --- ключові слова (рос + укр), регістронезалежно ---
_PROC_START = re.compile(
    r"^\s*(?:Процедура|Функция|Процедура|Функція)\b", re.IGNORECASE)
_PROC_END = re.compile(
    r"^\s*(?:КонецПроцедуры|КонецФункции|КінецьПроцедури|КінецьФункції)\b",
    re.IGNORECASE)
_DIRECTIVE = re.compile(r"^\s*&", re.IGNORECASE)
_VAR = re.compile(r"^\s*(?:Перем|Перем)\b", re.IGNORECASE)
_REGION = re.compile(
    r"^\s*#\s*(?:Область|КонецОбласти|Область|КінецьОбласті)\b", re.IGNORECASE)
_PREPROC = re.compile(
    r"^\s*#\s*(?:Если|Тогда|Иначе|ИначеЕсли|КонецЕсли|"
    r"Якщо|Тоді|Інакше|ІнакшеЯкщо|КінецьЯкщо)\b", re.IGNORECASE)

# ім'я процедури/функції та прапорець Экспорт
_PROC_SIG = re.compile(
    r"^\s*(?:(?P<kind_ru>Процедура|Функция)|(?P<kind_ua>Процедура|Функція))\s+"
    r"(?P<name>[A-Za-zА-Яа-яЁёЇїІіЄєҐґ_][\w]*)\s*\(",
    re.IGNORECASE)
_EXPORT = re.compile(r"\bЭкспорт\b|\bЕкспорт\b", re.IGNORECASE)


@dataclass
class ScannedLine:
    no: int          # номер рядка (1-based)
    raw: str         # оригінальний рядок
    kind: LineKind
    in_string_cont: bool  # рядок є продовженням багаторядкового літерала


def _strip_code_part(line: str, in_string: bool) -> tuple[str, bool]:
    """
    Повертає (код_поза_рядками_й_коментарями, чи_відкритий_рядок_у_кінці).

    Прибирає вміст рядкових літералів і коментарів, щоб подальші перевірки
    ключових слів працювали лише по «справжньому» коду.
    """
    out = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if in_string:
            if ch == '"':
                # подвоєні лапки — екранування всередині рядка
                if i + 1 < n and line[i + 1] == '"':
                    i += 2
                    continue
                in_string = False
                i += 1
                continue
            i += 1
            continue
        # не в рядку
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == '/' and i + 1 < n and line[i + 1] == '/':
            break  # коментар до кінця рядка
        out.append(ch)
        i += 1
    return "".join(out), in_string


def scan(text: str) -> list[ScannedLine]:
    """Класифікує кожен рядок модуля з урахуванням стану рядків/коментарів."""
    result: list[ScannedLine] = []
    in_string = False

    for idx, raw in enumerate(text.splitlines(), start=1):
        line_starts_in_string = in_string
        code_part, in_string = _strip_code_part(raw, in_string)

        # якщо рядок — продовження багаторядкового літерала, це тіло (CODE)
        if line_starts_in_string:
            result.append(ScannedLine(idx, raw, LineKind.CODE, True))
            continue

        stripped = raw.strip()
        code_stripped = code_part.strip()

        if not stripped:
            kind = LineKind.BLANK
        elif not code_stripped and stripped.startswith("//"):
            kind = LineKind.DOC_COMMENT
        elif _REGION.match(raw):
            kind = LineKind.REGION
        elif _PREPROC.match(raw):
            kind = LineKind.PREPROC
        elif _DIRECTIVE.match(raw):
            kind = LineKind.DIRECTIVE
        elif _PROC_START.match(code_part):
            kind = LineKind.PROC_START
        elif _PROC_END.match(code_part):
            kind = LineKind.PROC_END
        elif _VAR.match(code_part):
            kind = LineKind.VAR
        else:
            kind = LineKind.CODE

        result.append(ScannedLine(idx, raw, kind, False))

    return result


def parse_signature(line: str) -> tuple[str | None, bool]:
    """З рядка PROC_START дістає (ім'я, is_export). Ім'я — None, якщо не впізнано."""
    m = _PROC_SIG.match(line)
    name = m.group("name") if m else None
    is_export = bool(_EXPORT.search(line))
    return name, is_export
