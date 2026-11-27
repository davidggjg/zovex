#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_kurigram_compat2 — תיקון בוט ההעלאה תחת kurigram.

kurigram הסירה את הפרמטר quote מ-Message.reply_text/reply* (שם תגובה תמיד מצטטת
את ההודעה), ו-main.py קורא reply_text(..., quote=True) במסלול הקובץ של בוט ההעלאה
⇒ TypeError לפני כל תשובה. כאן: עוטפים את מתודות ה-reply* של Message — quote נזרק
(ההתנהגות זהה: מצטט), reply_to_message_id → reply_parameters,
disable_web_page_preview → link_preview_options. על Pyrogram — לא פעיל.
    python3 fix_kurigram_compat2.py [--check|--revert]"""
import os, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_kurigram_compat2]"
A = "        Client.get_dc_option = _kc_gdo\n"
N = A + '''        # [fix_kurigram_compat2] פרמטרים שהוסרו ב-kurigram (quote וכו')
        import functools as _kc_ft
        from pyrogram import types as _kc_types
        from pyrogram.types import Message as _KC_Msg

        def _kc_fix_kwargs(fn):
            try:
                _p = _kc_insp.signature(fn).parameters
            except Exception:
                return fn
            if any(x.kind == x.VAR_KEYWORD for x in _p.values()):
                return fn

            @_kc_ft.wraps(fn)
            def _w(*a, **kw):          # לא async: kurigram עוטפת ב-sync wrapper; מחזירים את מה שהיא מחזירה
                if "quote" in kw and "quote" not in _p:
                    kw.pop("quote")
                if "reply_to_message_id" in kw and "reply_to_message_id" not in _p:
                    _mid = kw.pop("reply_to_message_id")
                    if _mid and "reply_parameters" in _p:
                        kw["reply_parameters"] = _kc_types.ReplyParameters(message_id=_mid)
                if "disable_web_page_preview" in kw and "disable_web_page_preview" not in _p:
                    _d = kw.pop("disable_web_page_preview")
                    if _d and "link_preview_options" in _p:
                        kw["link_preview_options"] = _kc_types.LinkPreviewOptions(is_disabled=True)
                return fn(*a, **kw)
            return _w

        for _kc_n in [n for n in dir(_KC_Msg) if n.startswith("reply")]:
            _kc_f = getattr(_KC_Msg, _kc_n, None)
            if callable(_kc_f):
                setattr(_KC_Msg, _kc_n, _kc_fix_kwargs(_kc_f))
        for _kc_n in ("send_message", "edit_message_text", "send_video", "send_document", "send_photo"):
            _kc_f = getattr(Client, _kc_n, None)
            if callable(_kc_f):
                setattr(Client, _kc_n, _kc_fix_kwargs(_kc_f))
'''
def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        out = src.replace(N, A, 1); compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_kcompat2"); open(PATH, "w", encoding="utf-8").write(out); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    assert src.count(A) == 1, "שכבת ההתאמה הראשונה (fix_kurigram_compat) לא מותקנת"
    out = src.replace(A, N, 1); compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_kcompat2"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_kcompat2"); return 0
if __name__ == "__main__": sys.exit(main())
