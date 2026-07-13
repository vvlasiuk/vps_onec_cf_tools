"""
Побудова «скелета» модуля й винесення тіл процедур.

Скелет — нормалізований, збитковий огляд модуля для дешевого читання:
директиви, повні сигнатури, оголошення Перем, регіони, доккоментарі-заголовки
процедур; замість тіла — тег-покажчик на файл із тілом та розмір у рядках.

Тіла процедур виносяться цілими (від сигнатури до КонецПроцедуры) окремими
одиницями. Короткі процедури (<= inline_threshold значущих рядків) лишаються
в скелеті інлайн — виносити їх невигідно (покажчик коштує як саме тіло).

Реконструкція назад НЕ підтримується: скелет збитковий, тіла — вірні оригіналу.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from onec_ctx.bsl.scanner import scan, parse_signature, LineKind, ScannedLine


@dataclass
class Procedure:
    name: str
    is_export: bool
    start_line: int          # рядок сигнатури (1-based)
    end_line: int            # рядок КонецПроцедуры
    directive: str | None    # &НаКлиенте тощо, якщо був безпосередньо перед
    doc_lines: list[str]     # заголовкові коментарі безпосередньо перед
    body_text: str           # уся процедура цілком (сигнатура..КонецПроцедуры)
    significant_lines: int   # значущих рядків у тілі (без порожніх/коментарів)
    inlined: bool = False


@dataclass
class ModuleModel:
    procedures: list[Procedure] = field(default_factory=list)
    var_decls: list[str] = field(default_factory=list)     # Перем ... на рівні модуля
    collisions: list[str] = field(default_factory=list)     # дубль імен у модулі


def _significant(lines: list[ScannedLine]) -> int:
    return sum(1 for sl in lines
               if sl.kind not in (LineKind.BLANK, LineKind.DOC_COMMENT))


def build_model(text: str) -> ModuleModel:
    """Розбирає текст модуля в модель процедур + модульних оголошень."""
    scanned = scan(text)
    model = ModuleModel()
    seen: dict[str, int] = {}

    i = 0
    n = len(scanned)
    # модульні Перем — до першої процедури/директиви
    while i < n and scanned[i].kind in (
            LineKind.BLANK, LineKind.DOC_COMMENT, LineKind.VAR,
            LineKind.REGION, LineKind.PREPROC):
        if scanned[i].kind == LineKind.VAR:
            model.var_decls.append(scanned[i].raw.strip())
        i += 1

    i = 0
    while i < n:
        sl = scanned[i]
        if sl.kind == LineKind.PROC_START:
            # зібрати попередні директиву й доккоментарі
            directive = None
            doc: list[str] = []
            j = len(model.procedures)  # not used; keep simple
            k = i - 1
            # доккоментарі безпосередньо над (можливо з директивою між ними)
            back: list[ScannedLine] = []
            while k >= 0 and scanned[k].kind in (
                    LineKind.DOC_COMMENT, LineKind.DIRECTIVE, LineKind.BLANK):
                back.append(scanned[k])
                k -= 1
            back.reverse()
            for b in back:
                if b.kind == LineKind.DIRECTIVE:
                    directive = b.raw.strip()
                elif b.kind == LineKind.DOC_COMMENT:
                    doc.append(b.raw.rstrip())
                # BLANK ігноруємо у зборі

            # знайти кінець процедури
            end = i
            body: list[ScannedLine] = [sl]
            m = i + 1
            while m < n and scanned[m].kind != LineKind.PROC_END:
                body.append(scanned[m])
                m += 1
            if m < n:  # рядок КонецПроцедуры
                body.append(scanned[m])
                end = m
            else:
                end = m - 1  # незакрита процедура (битий модуль) — беремо до кінця

            name, is_export = parse_signature(sl.raw)
            name = name or f"<анонім@{sl.no}>"

            # колізія імені в межах модуля
            if name in seen:
                model.collisions.append(
                    f"{name} (рядки {seen[name]} та {sl.no})")
            else:
                seen[name] = sl.no

            body_text = "\n".join(b.raw for b in body)
            sig_cnt = _significant(body[1:-1] if len(body) >= 2 else [])

            model.procedures.append(Procedure(
                name=name, is_export=is_export,
                start_line=sl.no, end_line=body[-1].no,
                directive=directive, doc_lines=doc,
                body_text=body_text, significant_lines=sig_cnt,
            ))
            i = end + 1
            continue
        i += 1

    return model


def _end_keyword(sig_line: str) -> str:
    low = sig_line.lstrip().lower()
    return "КонецФункции" if low.startswith(("функц", "функ")) else "КонецПроцедуры"


def render_full(model: ModuleModel, inline_threshold: int = 3) -> str:
    """
    Повний кістяк: доккоментарі-заголовки, директиви, повні сигнатури.
    Короткі процедури лишаються інлайн; довгі — сигнатура + позначка розміру
    (тіло дістається окремо за іменем через маніфест).
    """
    out: list[str] = []
    if model.var_decls:
        out.extend(model.var_decls)
        out.append("")
    for p in model.procedures:
        out.extend(p.doc_lines)
        if p.directive:
            out.append(p.directive)
        sig_line = p.body_text.splitlines()[0]
        if p.significant_lines <= inline_threshold:
            p.inlined = True
            out.append(p.body_text)
        else:
            out.append(sig_line)
            out.append(f"    // тіло: {p.significant_lines} значущих рядків "
                       f"(рядки {p.start_line}-{p.end_line})")
            out.append(_end_keyword(sig_line))
        out.append("")
    return "\n".join(out)


def render_compact(model: ModuleModel) -> str:
    """
    Компактний кістяк: лише директиви + сигнатури + Кінець, без доккоментарів
    і без тіл. Швидкий огляд форми API модуля.
    """
    out: list[str] = []
    if model.var_decls:
        out.extend(model.var_decls)
        out.append("")
    for p in model.procedures:
        if p.directive:
            out.append(p.directive)
        sig_line = p.body_text.splitlines()[0]
        out.append(sig_line)
        out.append(_end_keyword(sig_line))
    return "\n".join(out)
