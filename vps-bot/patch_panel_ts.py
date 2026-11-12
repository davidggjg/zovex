#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_panel_ts — "המר לרלֵיי" בפאנל מזהה קישור TS גולמי (בלי סיומת / .ts)
ומייצר את מסלול ההמרה ל-HLS: ‎/hls-relay/_fix/<host>/<path>/__ts.m3u8‎.
דורש fix_relay_ts.py בשרת. admin.html בלבד.   PANEL=... python3 patch_panel_ts.py [--check|--revert]"""
import os, shutil, sys
PATH = os.environ.get("PANEL", "/opt/zovex-bot/admin.html")
MARKER = "[fix_relay_ts]"
E = [
 ('  el.value=location.origin+"/hls-relay/"+seg+u.pathname+(u.search||"");',
  '  // [fix_relay_ts] קישור בלי סיומת (פאנל Xtream) או ‎.ts‎ הוא זרם TS גולמי:\n'
  '  // דפדפן לא מנגן אותו, ולכן מנתבים להמרה ל-HLS בשרת.\n'
  '  const _last=u.pathname.split("/").pop();\n'
  '  const _isTs = !u.search && (_last.indexOf(".")<0 || /\\.ts$/i.test(_last));\n'
  '  el.value = _isTs\n'
  '    ? location.origin+"/hls-relay/_fix/"+seg+u.pathname.replace(/\\/$/,"")+"/__ts.m3u8"\n'
  '    : location.origin+"/hls-relay/"+seg+u.pathname+(u.search||"");'),
 ('                                     : "✓ הומר לרלֵיי, כולל פורט "+u.port;',
  '                                     : "✓ הומר לרלֵיי, כולל פורט "+u.port;\n'
  '  if(_isTs) msg.textContent += " · זרם TS גולמי → מומר ל-HLS בשרת";'),
]
def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    s = open(PATH, encoding="utf-8").read(); bak = PATH + ".bak_panel_ts"
    if arg == "--revert":
        if MARKER not in s: print("אין מה לשחזר"); return 0
        shutil.copy2(bak, PATH); print("✓ שוחזר"); return 0
    if MARKER in s: print("✓ כבר מותקן"); return 0
    out = s
    for a, n in E:
        assert out.count(a) == 1, f"עוגן לא נמצא: {a[:50]}"
        out = out.replace(a, n, 1)
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    shutil.copy2(PATH, bak); open(PATH, "w", encoding="utf-8").write(out)
    print("✓ הוחל. גיבוי:", bak); return 0
if __name__ == "__main__": sys.exit(main())
