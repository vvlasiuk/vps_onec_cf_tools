"""
Обхід піддерева вивантаження й обробка модулів.

Розпізнає модулі за узором шляхів штатного вивантаження (перевірено на
реальному дереві УТП): .bsl читає напряму, Form.bin розпаковує в текст.
Для кожного модуля будує кістяк + виносить тіла, попутно збирає індекс
визначень (символ -> модуль + export).

Узори (роль модуля за іменем файла):
    ObjectModule.bsl        -> модуль об'єкта
    ManagerModule.bsl       -> модуль менеджера
    Module.bsl (CommonModules) / (Forms/.../Ext/Form/) -> спільний / модуль форми
    RecordSetModule.bsl     -> модуль набору запису
    ValueManagerModule.bsl  -> модуль менеджера значення
    CommandModule.bsl       -> модуль команди
    Form.bin                -> модуль звичайної форми (бінарний, розпакувати)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from onec_ctx.cf.form import extract_form_module_file
from onec_ctx.bsl.skeleton import build_model, ModuleModel

MODULE_FILENAMES = {
    "objectmodule.bsl": "модуль об'єкта",
    "managermodule.bsl": "модуль менеджера",
    "module.bsl": "модуль (спільний/форми)",
    "recordsetmodule.bsl": "модуль набору запису",
    "valuemanagermodule.bsl": "модуль менеджера значення",
    "commandmodule.bsl": "модуль команди",
    "managedapplicationmodule.bsl": "модуль керованого застосунку",
    "ordinaryapplicationmodule.bsl": "модуль звичайного застосунку",
    "sessionmodule.bsl": "модуль сеансу",
    "externalconnectionmodule.bsl": "модуль зовнішнього з'єднання",
}


@dataclass
class ModuleEntry:
    path: str                # відносний шлях у дереві
    role: str                # людська роль модуля
    source: str              # 'bsl' | 'form.bin'
    text: str | None         # текст модуля (None якщо не витягся)
    model: ModuleModel | None = None
    error: str | None = None


@dataclass
class Symbol:
    name: str
    is_export: bool
    module_path: str


def classify(path: str) -> tuple[str, str] | None:
    """Повертає (роль, джерело) або None, якщо файл — не модуль."""
    base = os.path.basename(path).lower()
    if base == "form.bin":
        return ("модуль звичайної форми", "form.bin")
    if base in MODULE_FILENAMES:
        return (MODULE_FILENAMES[base], "bsl")
    return None


def _read_bsl(path: str) -> str:
    with open(path, "rb") as fh:
        data = fh.read()
    for enc in ("utf-8-sig", "utf-8", "utf-16-le", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def walk_tree(root: str) -> list[ModuleEntry]:
    """Обходить дерево, повертає список модулів (з текстом і моделлю)."""
    entries: list[ModuleEntry] = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            full = os.path.join(dirpath, fn)
            cls = classify(full)
            if not cls:
                continue
            role, source = cls
            rel = os.path.relpath(full, root)
            entry = ModuleEntry(path=rel, role=role, source=source, text=None)
            try:
                if source == "form.bin":
                    entry.text = extract_form_module_file(full)
                else:
                    entry.text = _read_bsl(full)
                if entry.text and entry.text.strip():
                    entry.model = build_model(entry.text)
            except Exception as exc:  # noqa: BLE001
                entry.error = str(exc)
            entries.append(entry)
    return entries


def build_symbol_index(entries: list[ModuleEntry]) -> list[Symbol]:
    """Індекс визначень: усі процедури/функції -> модуль + export."""
    symbols: list[Symbol] = []
    for e in entries:
        if not e.model:
            continue
        for p in e.model.procedures:
            symbols.append(Symbol(p.name, p.is_export, e.path))
    return symbols
