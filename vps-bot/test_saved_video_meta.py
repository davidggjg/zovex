#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בודק את fix_saved_video_meta.py מול main.py האמיתי, לפני שהוא נוגע בשרת.

הבדיקה הזאת קיימת בגלל תקלה אמיתית: תיקון קודם נבדק מול קובץ שנכתב במיוחד
לבדיקה, ובו היה "import pathlib". בקובץ האמיתי יש רק "from pathlib import
Path", ולכן הקוד נפל ב-NameError, השירות נכנס ללולאת קריסה והאתר ירד.
מכאן שתי המסקנות שמיושמות כאן:

  · הבדיקה רצה על main.py מהריפו — אותו קובץ שרץ בשרת — ולא על המצאה.
  · לא מספיק שהקוד מתקמפל. קומפילציה אינה מגלה NameError, שמתרחש רק בזמן
    ריצה. לכן נבדק גם שכל שם גלובלי שהקוד החדש משתמש בו באמת קיים במודול.

    python3 test_saved_video_meta.py
"""
import ast, builtins, importlib.util, pathlib, py_compile, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
MAIN = HERE / "main.py"

# הפונקציות שהתיקון יצר או נגע בהן — עליהן נבדקת רזולוציית השמות.
CHECKED = ["_saved_probe", "_saved_thumb", "_saved_send", "saved_upload"]


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fail(msg):
    print("❌ " + msg)
    sys.exit(1)


def collect_module_names(tree):
    """שמות שקיימים ברמת המודול: הגדרות, השמות וייבואים."""
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                names.update(n.id for n in ast.walk(t) if isinstance(n, ast.Name))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            names.update(n.id for n in ast.walk(node.target)
                         if isinstance(n, ast.Name))
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)
        elif isinstance(node, (ast.If, ast.Try, ast.With)):
            # ייבוא מותנה או בתוך try — נפוץ, ועדיין מגדיר שם ברמת המודול
            for sub in ast.walk(node):
                if isinstance(sub, ast.Import):
                    for a in sub.names:
                        names.add((a.asname or a.name).split(".")[0])
                elif isinstance(sub, ast.ImportFrom):
                    for a in sub.names:
                        names.add(a.asname or a.name)
                elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef)):
                    names.add(sub.name)
    return names


def local_names(fn):
    """שמות שנקשרים בתוך הפונקציה: פרמטרים, השמות, for, with, except, def."""
    out = set()
    args = fn.args
    for a in (list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)):
        out.add(a.arg)
    if args.vararg:
        out.add(args.vararg.arg)
    if args.kwarg:
        out.add(args.kwarg.arg)
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
            if node is not fn:
                a2 = getattr(node, "args", None)
                if a2:
                    for a in (list(a2.posonlyargs) + list(a2.args) +
                              list(a2.kwonlyargs)):
                        out.add(a.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.comprehension):
            out.update(n.id for n in ast.walk(node.target)
                       if isinstance(n, ast.Name))
    return out


def main():
    if not MAIN.exists():
        fail(f"לא נמצא {MAIN}")

    add = load("add_saved_upload")
    fix = load("fix_saved_video_meta")

    src = MAIN.read_text(encoding="utf-8")
    print(f"main.py מהריפו: {len(src.splitlines())} שורות")

    # ① מצב הפתיחה של השרת: main.py אחרי add_saved_upload.py
    if src.count(add.ANCHOR) != 1:
        fail("נקודת העיגון של add_saved_upload לא יחידה ב-main.py")
    staged = src.replace(add.ANCHOR,
                         add.BLOCK.lstrip("\n") + "\n" + add.ANCHOR, 1)
    print("✓ הוחל add_saved_upload.py (מצב השרת היום)")

    # ② התיקון הנבדק
    patched = fix.apply_edits(staged)
    print(f"✓ כל {len(fix.EDITS)} נקודות העיגון נמצאו בדיוק פעם אחת")

    # ③ מתקמפל
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as t:
        t.write(patched)
        tmp = t.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        fail(f"לא מתקמפל: {e}")
    print("✓ מתקמפל")

    # ④ כל שם גלובלי שהקוד החדש משתמש בו קיים במודול — הבדיקה שהייתה חסרה
    tree = ast.parse(patched)
    module_names = collect_module_names(tree)
    known = module_names | set(dir(builtins))
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    missing = []
    for name in CHECKED:
        fn = fns.get(name)
        if fn is None:
            fail(f"הפונקציה {name} לא נמצאה בקובץ המתוקן")
        bound = local_names(fn)
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in bound and node.id not in known:
                    missing.append((name, node.id, node.lineno))
    if missing:
        for fn_name, ident, line in missing:
            print(f"   {fn_name}: השם '{ident}' אינו מוגדר (שורה {line})")
        fail(f"{len(missing)} שמות לא פתירים — זה בדיוק ה-NameError שהפיל את השרת")
    print(f"✓ כל השמות ב-{', '.join(CHECKED)} נפתרים")

    # ⑤ הדבר הספציפי שהתיקון נועד לו
    for needle, why in (
            ("duration=_dur", "duration נשלח ל-send_video"),
            ('width=int(meta.get("width") or 0)', "width נשלח"),
            ('height=int(meta.get("height") or 0)', "height נשלח"),
            ("thumb=thumb or None", "תמונה ממוזערת נשלחת"),
            ('path.open("wb", buffering=1024 * 1024)', "חיץ הכתיבה"),
            ("import asyncio, hmac, os, pathlib, re, shutil, subprocess, time, uuid",
             "shutil ו-subprocess מיובאים במפורש")):
        if needle not in patched:
            fail(f"חסר בקובץ המתוקן: {why}")
    print("✓ תוכן התיקון קיים בפועל")

    # ⑥ אידמפוטנטיות: הרצה שנייה על קובץ מתוקן לא אמורה להתחיל בכלל
    if fix.DONE_MARK not in patched:
        fail("סימן ה'כבר הוחל' לא נמצא — הרצה שנייה הייתה משכפלת את התיקון")
    print("✓ הרצה שנייה תזוהה כ'כבר מוחל'")

    print()
    print("הכול עבר.")


if __name__ == "__main__":
    main()
