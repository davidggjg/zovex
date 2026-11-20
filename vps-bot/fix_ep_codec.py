#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ep_codec — תגיות איכות/קודק לא מזוהות יותר כמספר פרק.

## התקלה (נמדד)
  "Stitch.Head.2025.1080p.WEB-DL.DD5.1.x264.mp4" — סרט — נקלט כ-
  "Stitch Head 2025 Dd5 — עונה 1 פרק 264": אחרי החלפת נקודות ברווחים
  "DD5.1.x264" נהיה "1 x264", והתבנית ‎1x05‎ קראה אותו כעונה 1 פרק 264.
## התיקון
  לפני חיפוש סימון פרק, מוסרות מהשם תגיות טכניות שאינן חלק משם לעולם:
  קודקים (x264/x265/H 264/HEVC/AVC), שמע (DD5 1/DDP/AAC2 0/AC3/DTS/Atmos),
  רזולוציה (1080p/2160p/4K), מקור (WEB-DL/WEBRip/BluRay/HDTV...), עומק צבע.
    MAIN_PY=... python3 fix_ep_codec.py [--check|--revert]
"""
import os, shutil, sys
PATH = os.environ.get("MAIN_PY", "/opt/zovex-bot/main.py")
MARKER = "[fix_ep_codec]"
A_DEF = "_EP_PATTERNS = [\n"
N_DEF = r'''# [fix_ep_codec] תגיות טכניות שאינן שם לעולם — מוסרות לפני חיפוש סימון פרק,
# אחרת "DD5.1.x264" → "1 x264" נקרא כעונה 1 פרק 264.
_CODEC_TAGS = re.compile(
    r"\b(?:[xh]\s?26[45]|hevc|avc|xvid|divx|av1|vp9|"
    r"dd\+?\s?[257]\s?[01]|ddp\s?[257]\s?[01]|e?ac3|aac\s?[257]?(?:\s?[01])?|dts(?:\s?hd)?|truehd|atmos|flac|opus|"
    r"\d{3,4}p|4k|uhd|web\s?dl|webdl|webrip|web|bluray|blu\s?ray|brrip|bdrip|hdrip|dvdrip|hdtv|hdcam|camrip|"
    r"10\s?bit|8\s?bit|hdr10|hdr|sdr|remux|proper|repack)\b", re.I)
''' + A_DEF
A_USE = "    n = n.replace('.', ' ').replace('_', ' ').replace('-', ' ')\n    season = episode = None\n"
N_USE = ("    n = n.replace('.', ' ').replace('_', ' ').replace('-', ' ')\n"
         "    n = re.sub(r'\\s+', ' ', _CODEC_TAGS.sub(' ', n)).strip()   # [fix_ep_codec]\n"
         "    season = episode = None\n")

def apply(src):
    if MARKER in src: print("✓ כבר מותקן"); return src
    for name, a in (("הגדרת התבניות", A_DEF), ("parse_episode_info", A_USE)):
        assert src.count(a) == 1, f"עוגן '{name}': נמצא {src.count(a)}"
    out = src.replace(A_DEF, N_DEF, 1).replace(A_USE, N_USE, 1)
    compile(out, "main.py", "exec"); return out

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = open(PATH, encoding="utf-8").read(); bak = PATH + ".bak_ep_codec"
    if arg == "--revert":
        if MARKER not in src: print("אין מה לשחזר"); return 0
        shutil.copy2(bak, PATH); print("✓ שוחזר"); return 0
    out = apply(src)
    if arg == "--check": print("✓ בדיקה עברה"); return 0
    if MARKER in src: return 0
    shutil.copy2(PATH, bak); open(PATH, "w", encoding="utf-8").write(out); print("✓ הוחל. גיבוי:", bak); return 0

if __name__ == "__main__": sys.exit(main())
