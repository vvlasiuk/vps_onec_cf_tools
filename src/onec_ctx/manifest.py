"""
Побудова маніфесту артефакту як єдиного SQLite-файла.

Увесь похідний матеріал (кістяки модулів + тіла процедур + навігація) лежить
в одній БД. Так на виході — один самодостатній файл замість файлового зоопарку
(десятки тисяч дрібних .bsl). vps_api відкриває його read-only й віддає зрізи
одним індексованим SELECT, без обходу диску й без парсингу в рантаймі.

Байт-точні оригінали лишаються в дереві вивантаження (джерело істини) — сюди
кладеться тільки похідне для читання. Реконструкція назад не підтримується.

Три рівні деталізації кістяка (щоб god-модуль не роздував контекст):
  - «зміст»    — з таблиці symbols (лише імена + export), найдешевше;
  - «компакт»  — modules.skeleton_compact (сигнатури без доккоментарів);
  - «повний»   — modules.skeleton_full (з доккоментарями).
Тіло процедури — symbols.body за (module_path, name).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from onec_ctx.inventory import ModuleEntry
from onec_ctx.bsl.skeleton import render_full, render_compact

SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE modules (
    module_path      TEXT PRIMARY KEY,
    role             TEXT,
    source           TEXT,          -- 'bsl' | 'form.bin'
    proc_count       INTEGER,
    export_count     INTEGER,
    skeleton_full    TEXT,
    skeleton_compact TEXT
);

CREATE TABLE symbols (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    kind              TEXT,          -- 'Процедура' | 'Функция'
    is_export         INTEGER,       -- 0/1
    module_path       TEXT NOT NULL,
    sig               TEXT,          -- сигнатура одним рядком
    start_line        INTEGER,
    end_line          INTEGER,
    significant_lines INTEGER,
    inlined           INTEGER,       -- 1 якщо тіло лишилось інлайн у кістяку
    body              TEXT           -- уся процедура цілком
);

CREATE INDEX idx_symbols_name    ON symbols(name);
CREATE INDEX idx_symbols_module  ON symbols(module_path, is_export);
CREATE TABLE collisions (
    module_path TEXT,
    detail      TEXT
);
"""


def _kind(sig_line: str) -> str:
    low = sig_line.lstrip().lower()
    return "Функция" if low.startswith(("функц", "функ", "функція")) else "Процедура"


def build_manifest(entries: list[ModuleEntry], db_path: str,
                   *, source_tree: str, inline_threshold: int = 3,
                   generator_version: str = "0.1.0") -> dict:
    """Створює SQLite-маніфест з обробленого дерева. Повертає підсумкову статистику.

    Запис іде в тимчасовий файл поряд, а наприкінці — атомарна підміна цільового
    (os.replace). Так vps_api ніколи не натрапить на напівзаписаний маніфест:
    він бачить або старий цілий файл, або новий цілий.
    """
    tmp_path = db_path + ".tmp"
    # прибираємо недороблений залишок від попереднього обірваного запуску
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    conn = sqlite3.connect(tmp_path)
    conn.executescript(SCHEMA)
    cur = conn.cursor()

    stats = {"modules": 0, "empty": 0, "errors": 0, "forms": 0,
             "procedures": 0, "exported": 0, "collisions": 0}

    for e in entries:
        if e.source == "form.bin":
            stats["forms"] += 1
        if e.error:
            stats["errors"] += 1
            continue
        if not (e.text and e.text.strip()) or not e.model:
            stats["empty"] += 1
            continue

        model = e.model
        full = render_full(model, inline_threshold=inline_threshold)
        compact = render_compact(model)
        exp_count = sum(1 for p in model.procedures if p.is_export)

        cur.execute(
            "INSERT INTO modules(module_path, role, source, proc_count, "
            "export_count, skeleton_full, skeleton_compact) VALUES (?,?,?,?,?,?,?)",
            (e.path, e.role, e.source, len(model.procedures),
             exp_count, full, compact))

        for p in model.procedures:
            sig_line = p.body_text.splitlines()[0]
            cur.execute(
                "INSERT INTO symbols(name, kind, is_export, module_path, sig, "
                "start_line, end_line, significant_lines, inlined, body) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (p.name, _kind(sig_line), int(p.is_export), e.path,
                 sig_line.strip(), p.start_line, p.end_line,
                 p.significant_lines, int(p.inlined), p.body_text))

        for c in model.collisions:
            cur.execute("INSERT INTO collisions(module_path, detail) VALUES (?,?)",
                        (e.path, c))

        stats["modules"] += 1
        stats["procedures"] += len(model.procedures)
        stats["exported"] += exp_count
        stats["collisions"] += len(model.collisions)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_tree": source_tree,
        "generator_version": generator_version,
        "modules": str(stats["modules"]),
        "procedures": str(stats["procedures"]),
        "exported": str(stats["exported"]),
    }
    cur.executemany("INSERT INTO meta(key, value) VALUES (?,?)", meta.items())

    conn.commit()
    conn.close()

    # атомарна підміна: у межах одного диска os.replace неподільний
    os.replace(tmp_path, db_path)
    return stats