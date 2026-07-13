"""
Перевірка згенерованого manifest.sqlite (тільки читання).

Показує: метадані, розміри таблиць, розподіл модулів за роллю, топ god-модулів,
приклади всіх типів запитів. Нічого не змінює.

Запуск:
    python check_manifest.py D:\\temp\\manifest.sqlite
    python check_manifest.py D:\\temp\\manifest.sqlite --symbol ОбщегоНазначения
"""
import argparse
import os
import sqlite3
import sys


def human(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--symbol", help="перевірити пошук конкретного символу")
    ap.add_argument("--module", help="показати зміст конкретного модуля")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"Файла немає: {args.db}")
        return 1

    print(f"Файл: {args.db}  ({human(os.path.getsize(args.db))})")
    c = sqlite3.connect(args.db)
    c.row_factory = sqlite3.Row

    # 1) цілісність
    integ = c.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"integrity_check: {integ}")

    # 2) таблиці на місці
    tables = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    print("таблиці:", ", ".join(sorted(tables)))

    # 3) метадані
    print("\n--- meta ---")
    for r in c.execute("SELECT key, value FROM meta"):
        print(f"  {r['key']}: {r['value']}")

    # 4) розміри
    print("\n--- лічильники ---")
    for t in ("modules", "symbols", "collisions"):
        if t in tables:
            n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n}")
    exp = c.execute("SELECT COUNT(*) FROM symbols WHERE is_export=1").fetchone()[0]
    tot = c.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    print(f"  експортних символів: {exp} із {tot}")

    # 5) розподіл за роллю
    print("\n--- модулі за роллю ---")
    for r in c.execute(
            "SELECT role, COUNT(*) n FROM modules GROUP BY role ORDER BY n DESC"):
        print(f"  {r['n']:5}  {r['role']}")

    # 6) топ god-модулів
    print("\n--- топ-10 за кількістю процедур ---")
    for r in c.execute(
            "SELECT module_path, proc_count FROM modules "
            "ORDER BY proc_count DESC LIMIT 10"):
        print(f"  {r['proc_count']:4}  {r['module_path']}")

    # 7) колізії, якщо є
    if "collisions" in tables:
        col = c.execute("SELECT COUNT(*) FROM collisions").fetchone()[0]
        if col:
            print(f"\n--- КОЛІЗІЇ ({col}) ---")
            for r in c.execute("SELECT module_path, detail FROM collisions LIMIT 20"):
                print(f"  {r['module_path']}: {r['detail']}")

    # 8) точковий запит символу
    if args.symbol:
        print(f"\n--- де оголошено '{args.symbol}' (експортні) ---")
        found = False
        for r in c.execute(
                "SELECT name, module_path, is_export FROM symbols "
                "WHERE name=? AND is_export=1", (args.symbol,)):
            print(f"  {r['name']}  <-  {r['module_path']}")
            found = True
        if not found:
            print("  (серед експортних не знайдено; спробуйте без фільтра export)")

    # 9) зміст модуля
    if args.module:
        print(f"\n--- зміст модуля '{args.module}' ---")
        for r in c.execute(
                "SELECT name, kind, is_export FROM symbols WHERE module_path=?",
                (args.module,)):
            exp = " [Экспорт]" if r["is_export"] else ""
            print(f"  {r['kind']} {r['name']}{exp}")

    c.close()
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())