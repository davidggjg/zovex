#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_locales — שפה שמוצעת חייבת להיות שלמה ולא רק קיימת.

שלוש בדיקות, וכולן נדרשות:

  כיסוי      כל מפתח שיש באנגלית קיים גם כאן
  מצייני מקום ‎{name}‎ ו-‎{n}‎ זהים בדיוק לאנגלית
  תגי HTML   אותם תגים, באותה כמות

השתיים האחרונות אינן קפדנות יתר. מציין מקום שאבד בתרגום אינו שגיאת
ניסוח — הוא הודעה שבורה אצל המשתמש ("נמחקו {n} הודעות" בלי המספר),
ותג שנפתח ולא נסגר מפיל את כל ההודעה בטלגרם. שתיהן מתגלות רק בשטח,
ולכן הן נבדקות כאן.
"""
from __future__ import annotations

import re
import sys

import i18n
import langs as lang

PASS = FAIL = 0
FAILURES: list[str] = []

_RX_PH = re.compile(r"\{([a-z_]+)\}")
_RX_TAG = re.compile(r"</?([a-z]+)>")


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  ✗ {name}   {detail[:120]}")


def section(t: str) -> None:
    print(f"\n── {t} ──")


def main() -> int:
    en = i18n.STRINGS["en"]
    for lg in lang.FULL:
        section(f"{lg} · {i18n.LANG_NAMES.get(lg, lg)}")
        table = i18n.STRINGS.get(lg, {})
        missing = [k for k in en if k not in table]
        ok(f"{lg}: כיסוי מלא", not missing,
           f"חסרים {len(missing)}: {missing[:5]}")

        bad_ph, bad_tag, empty = [], [], []
        for k, v in en.items():
            mine = table.get(k)
            if mine is None:
                continue
            if not mine.strip():
                empty.append(k)
            if sorted(_RX_PH.findall(v)) != sorted(_RX_PH.findall(mine)):
                bad_ph.append(k)
            if sorted(_RX_TAG.findall(v)) != sorted(_RX_TAG.findall(mine)):
                bad_tag.append(k)
        ok(f"{lg}: מצייני מקום זהים", not bad_ph,
           f"{len(bad_ph)}: {bad_ph[:5]}")
        ok(f"{lg}: תגי HTML זהים", not bad_tag,
           f"{len(bad_tag)}: {bad_tag[:5]}")
        ok(f"{lg}: אין מחרוזות ריקות", not empty, str(empty[:5]))

    print(f"\n{'─' * 46}")
    print(f"עברו {PASS} · נכשלו {FAIL}")
    if FAILURES:
        print("נכשלו: " + ", ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
