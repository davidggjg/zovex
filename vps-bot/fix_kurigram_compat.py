#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_kurigram_compat — שכבת התאמה שמאפשרת לאותו main.py לרוץ גם על Pyrogram 2.0.106
וגם על kurigram (הממשיכה המתוחזקת). על Pyrogram — לא עושה כלום.

הבדלים שנמצאו בקוד של kurigram 2.2.27 ומטופלים כאן:
  1. Session(...) ו-Auth(...) דורשים server_address ו-port. main.py קורא להם בחתימה
     הישנה ⇒ עוטפים אותם ומספקים כתובת.
  2. kurigram לוקחת כתובות מ-help.GetConfig ולא מטבלה ⇒ העקיפה של DC4 media
     (fix_dc_media_addr, TG_MEDIA_DC_SKIP) לא הייתה חלה, וההורדות היו חוזרות
     לכתובת החסומה. כאן: אותה טבלת כתובות בדיוק של Pyrogram 2.0.106, עם הדילוג,
     גם בחיבורים שלנו וגם ב-Client.get_dc_option של הספרייה.
    python3 fix_kurigram_compat.py [--check|--revert]"""
import os, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_kurigram_compat]"
A = "from pyrogram.session import Session, Auth\n"
N = A + '''# ── [fix_kurigram_compat] התאמה ל-kurigram (על Pyrogram 2.0.106 — לא פעיל) ──
try:
    import inspect as _kc_insp
    if "server_address" in _kc_insp.signature(Session.__init__).parameters:
        _KC_SKIP = {int(x) for x in os.environ.get("TG_MEDIA_DC_SKIP", "4").split(",") if x.strip()}
        _KC_PROD = {1: "149.154.175.53", 2: "149.154.167.51", 3: "149.154.175.100",
                    4: "149.154.167.91", 5: "91.108.56.130", 203: "91.105.192.100"}
        _KC_PROD_MEDIA = {2: "149.154.167.151", 4: "149.154.164.250"}
        _KC_TEST = {1: "149.154.175.10", 2: "149.154.167.40", 3: "149.154.175.117"}

        def _kc_addr(dc_id, test_mode, media):
            if test_mode:
                return _KC_TEST[dc_id], 80
            if media and dc_id not in _KC_SKIP and dc_id in _KC_PROD_MEDIA:
                return _KC_PROD_MEDIA[dc_id], 443
            return _KC_PROD[dc_id], 443

        _KC_Session, _KC_Auth = Session, Auth

        class Session(_KC_Session):  # noqa: F811
            def __init__(self, client, dc_id, *args, **kw):
                if args and isinstance(args[0], (bytes, bytearray)):      # חתימה ישנה
                    auth_key, test_mode = args[0], args[1]
                    is_media = kw.pop("is_media", args[2] if len(args) > 2 else False)
                    addr, port = _kc_addr(dc_id, test_mode, is_media)
                    super().__init__(client, dc_id, addr, port, auth_key, test_mode,
                                     is_media=is_media, **kw)
                else:
                    super().__init__(client, dc_id, *args, **kw)

        class Auth(_KC_Auth):  # noqa: F811
            def __init__(self, client, dc_id, *args, **kw):
                if len(args) == 1 and not kw:                                # (client, dc, test_mode)
                    addr, port = _kc_addr(dc_id, args[0], False)
                    super().__init__(client, dc_id, addr, port, args[0])
                else:
                    super().__init__(client, dc_id, *args, **kw)

        _kc_orig_gdo = Client.get_dc_option

        async def _kc_gdo(self, dc_id=None, is_media=False, is_cdn=False, ipv6=False):
            if dc_id in _KC_SKIP:
                is_media = False
                is_cdn = False
            return await _kc_orig_gdo(self, dc_id, is_media=is_media, is_cdn=is_cdn, ipv6=ipv6)

        Client.get_dc_option = _kc_gdo
        logging.getLogger(__name__).info("kurigram compat פעיל (דילוג media ל-DC %s)", sorted(_KC_SKIP))
except Exception as _kc_e:
    logging.getLogger(__name__).warning("kurigram compat: %s", _kc_e)
'''
def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read()
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        out = src.replace(N, A, 1); compile(out, "main.py", "exec")
        shutil.copy2(PATH, PATH + ".bak_kcompat"); open(PATH, "w", encoding="utf-8").write(out); print("✓ שוחזר"); return 0
    if MARKER in src: print("✓ כבר מותקן"); return 0
    assert src.count(A) == 1, "עוגן ה-import של Session/Auth לא נמצא"
    assert src.index("from pyrogram import Client") < src.index(A), "Client לא מיובא לפני Session"
    assert "import logging" in src[:src.index(A)] or "\nimport logging" in src, "logging לא מיובא"
    out = src.replace(A, N, 1); compile(out, "main.py", "exec")
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, PATH + ".bak_kcompat"); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", PATH + ".bak_kcompat"); return 0
if __name__ == "__main__": sys.exit(main())
