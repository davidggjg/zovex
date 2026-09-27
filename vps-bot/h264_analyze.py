#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""h264_analyze.py — מה באמת יש בזרם H.264, ברמת יחידת ה-NAL והכותרת.

## למה כלי ולא עוד השערה

ערוץ אחד מתנגן חלק ב-Firefox ולא מתנגן ב-Chrome, כשבשניהם רץ אותו קוד
שלנו ואותו Shaka מעל MSE. "אין IDR" הוא מה שמדדתי, אבל הוא אינו מסביר
את ההבדל בין שני הדפדפנים — ולכן הוא לא יכול להיות ההסבר המלא.

מה שנדרש כדי לענות זה מה שיושב **בתוך** הזרם: אילו סוגי NAL יש, איזה
slice_type לכל פרוסה, האם יש recovery point SEI, האם הפרוסה הראשונה
בכל סגמנט היא I, וכמה פרוסות יש לפריים. ffprobe אינו נותן את זה —
הדגל key_frame שלו דולק גם על I-slice שאינו IDR, וכבר הטעה כאן פעם
אחת: הוא דיווח 7 "מפתחות" בסגמנט שבו מספר ה-IDR האמיתי הוא אפס.

הכלי הזה קורא את ה-bitstream עצמו: מפצל Annex B, מסיר בתי מניעת חיקוי,
וקורא את הכותרות ב-exp-Golomb.

    python3 h264_analyze.py <קובץ.ts | קובץ.264 | כתובת m3u8>
    python3 h264_analyze.py <כתובת> --seconds 12
    python3 h264_analyze.py <קובץ> --frames 40      # פירוט פרוסה-פרוסה
"""
import argparse
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

NAL_NAMES = {
    1: "slice (לא IDR)", 2: "DPA", 3: "DPB", 4: "DPC", 5: "IDR",
    6: "SEI", 7: "SPS", 8: "PPS", 9: "AUD", 10: "סוף רצף",
    11: "סוף זרם", 12: "מילוי", 13: "SPS-ext", 19: "slice עזר",
}
SLICE_TYPES = {0: "P", 1: "B", 2: "I", 3: "SP", 4: "SI",
               5: "P*", 6: "B*", 7: "I*", 8: "SP*", 9: "SI*"}
SEI_NAMES = {0: "buffering period", 1: "pic timing", 2: "pan scan",
             3: "filler", 4: "user data registered",
             5: "user data unregistered", 6: "recovery point ★",
             45: "frame packing"}


class Bits:
    """קורא ביטים עם exp-Golomb. עובד על RBSP אחרי הסרת בתי מניעת חיקוי."""

    def __init__(self, data: bytes):
        self.d = data
        self.p = 0                      # מיקום בביטים

    def bit(self) -> int:
        if self.p >= len(self.d) * 8:
            raise EOFError
        b = (self.d[self.p >> 3] >> (7 - (self.p & 7))) & 1
        self.p += 1
        return b

    def bits(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v

    def ue(self) -> int:
        """Exp-Golomb ללא סימן."""
        z = 0
        while self.bit() == 0:
            z += 1
            if z > 32:
                raise ValueError("exp-Golomb פרוע")
        return (1 << z) - 1 + (self.bits(z) if z else 0)

    def se(self) -> int:
        k = self.ue()
        return (k + 1) // 2 if k % 2 else -(k // 2)


def rbsp(data: bytes) -> bytes:
    """מסיר בתי מניעת חיקוי (00 00 03 → 00 00). בלי זה כל כותרת
    שמכילה את הרצף הזה נקראת שגוי."""
    out = bytearray()
    i = 0
    while i < len(data):
        if (i + 2 < len(data) and data[i] == 0 and data[i + 1] == 0
                and data[i + 2] == 3):
            out += data[i:i + 2]
            i += 3
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def split_annexb(data: bytes):
    """מחזיר [(סוג, nal_ref_idc, גוף)…]. תומך בקוד פתיחה של 3 ו-4 בתים."""
    out = []
    starts = [m.start() for m in re.finditer(b"\x00\x00\x01", data)]
    for k, s in enumerate(starts):
        b = s + 3
        if b >= len(data):
            break
        e = starts[k + 1] if k + 1 < len(starts) else len(data)
        # קוד פתיחה של 4 בתים: ה-00 שלפניו שייך לקוד ולא לגוף
        while e > b and data[e - 1] == 0:
            e -= 1
        hdr = data[b]
        if hdr & 0x80:                  # forbidden_zero_bit — לא NAL תקין
            continue
        out.append(((hdr & 0x1F), (hdr >> 5) & 3, data[b + 1:e]))
    return out


def parse_sps(body: bytes) -> dict:
    r = Bits(rbsp(body))
    d = {}
    d["profile_idc"] = r.bits(8)
    flags = r.bits(8)
    d["constraint_set"] = flags >> 2
    d["level_idc"] = r.bits(8)
    d["sps_id"] = r.ue()
    if d["profile_idc"] in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135):
        d["chroma_format_idc"] = r.ue()
        if d["chroma_format_idc"] == 3:
            r.bit()
        r.ue(); r.ue(); r.bit()
        if r.bit():                     # seq_scaling_matrix_present
            for i in range(8 if d.get("chroma_format_idc") != 3 else 12):
                if r.bit():
                    last = nxt = 8
                    for _ in range(16 if i < 6 else 64):
                        if nxt:
                            nxt = (last + r.se() + 256) % 256
                        last = nxt or last
    d["log2_max_frame_num"] = r.ue() + 4
    d["pic_order_cnt_type"] = r.ue()
    if d["pic_order_cnt_type"] == 0:
        d["log2_max_poc_lsb"] = r.ue() + 4
    elif d["pic_order_cnt_type"] == 1:
        r.bit(); r.se(); r.se()
        for _ in range(r.ue()):
            r.se()
    d["max_num_ref_frames"] = r.ue()
    d["gaps_in_frame_num_allowed"] = r.bit()
    w = r.ue() + 1
    h = r.ue() + 1
    d["frame_mbs_only"] = r.bit()
    if not d["frame_mbs_only"]:
        r.bit()
    d["width"] = w * 16
    d["height"] = h * 16 * (2 - d["frame_mbs_only"])
    return d


def parse_slice(body: bytes) -> dict:
    r = Bits(rbsp(body))
    first_mb = r.ue()
    st = r.ue()
    return {"first_mb": first_mb, "slice_type": st,
            "name": SLICE_TYPES.get(st, str(st))}


def parse_sei(body: bytes):
    """מחזיר את סוגי מטעני ה-SEI. recovery point (6) הוא הקריטי:
    הוא מה שמאפשר למפענח סלחן להתחיל בלי IDR."""
    out, i = [], 0
    d = rbsp(body)
    while i < len(d):
        t = 0
        while i < len(d) and d[i] == 0xFF:
            t += 255; i += 1
        if i >= len(d):
            break
        t += d[i]; i += 1
        size = 0
        while i < len(d) and d[i] == 0xFF:
            size += 255; i += 1
        if i >= len(d):
            break
        size += d[i]; i += 1
        out.append(t)
        i += size
        if t == 0x80:                   # rbsp trailing
            break
    return out


def fetch(target: str, seconds: int) -> bytes:
    """מחזיר זרם Annex B. כתובת/ts עוברים דרך ffmpeg עם -c copy."""
    if target.startswith("http"):
        src = target
    elif Path(target).suffix == ".264":
        return Path(target).read_bytes()
    else:
        src = target
    tmp = Path(tempfile.mkdtemp()) / "es.264"
    cmd = ["ffmpeg", "-hide_banner", "-v", "error"]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += ["-i", src, "-map", "0:v:0", "-c", "copy", "-f", "h264", str(tmp)]
    r = subprocess.run(cmd, capture_output=True, timeout=180)
    if not tmp.exists() or not tmp.stat().st_size:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        sys.exit(f"ffmpeg לא הפיק זרם (rc={r.returncode})\n{err[-500:]}")
    return tmp.read_bytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--frames", type=int, default=0,
                    help="לפרט את N הפרוסות הראשונות")
    a = ap.parse_args()

    data = fetch(a.target, a.seconds)
    nals = split_annexb(data)
    print(f"  זרם: {len(data):,} בתים · {len(nals)} יחידות NAL\n")

    types = Counter(t for t, _, _ in nals)
    print("  ── סוגי NAL ──")
    for t in sorted(types):
        print(f"     {t:<3} {NAL_NAMES.get(t, 'אחר'):<18} ×{types[t]}")

    # SPS
    sps = next((b for t, _, b in nals if t == 7), None)
    if sps:
        try:
            d = parse_sps(sps)
            print("\n  ── SPS ──")
            print(f"     profile={d['profile_idc']} level={d['level_idc']} "
                  f"{d['width']}x{d['height']}")
            print(f"     pic_order_cnt_type={d['pic_order_cnt_type']} · "
                  f"max_num_ref_frames={d['max_num_ref_frames']}")
            print(f"     gaps_in_frame_num_allowed={d['gaps_in_frame_num_allowed']} · "
                  f"frame_mbs_only={d['frame_mbs_only']}")
        except Exception as e:
            print(f"\n  ── SPS: לא נותח ({type(e).__name__}) ──")

    # SEI
    seis = Counter()
    for t, _, b in nals:
        if t == 6:
            for p in parse_sei(b):
                seis[p] += 1
    if seis:
        print("\n  ── SEI ──")
        for p in sorted(seis):
            print(f"     {p:<4} {SEI_NAMES.get(p, 'אחר'):<26} ×{seis[p]}")
    rec = seis.get(6, 0)

    # פרוסות
    slices, bad = [], 0
    for t, ref, b in nals:
        if t in (1, 5):
            try:
                s = parse_slice(b)
                s["idr"] = (t == 5)
                s["ref"] = ref
                slices.append(s)
            except Exception:
                bad += 1
    st = Counter(s["name"] for s in slices)
    print(f"\n  ── פרוסות ({len(slices)}" + (f", {bad} לא נותחו" if bad else "") + ") ──")
    for k in sorted(st):
        print(f"     {k:<4} ×{st[k]}")
    firsts = [s for s in slices if s["first_mb"] == 0]
    print(f"     פריימים (first_mb=0): {len(firsts)} · "
          f"פרוסות לפריים: {len(slices)/max(len(firsts),1):.1f}")
    i_frames = [s for s in firsts if s["name"].startswith("I")]
    print(f"     פריימי I: {len(i_frames)} · מהם IDR: "
          f"{sum(1 for s in i_frames if s['idr'])}")

    if a.frames:
        print(f"\n  ── {a.frames} הפרוסות הראשונות ──")
        for s in slices[:a.frames]:
            print(f"     first_mb={s['first_mb']:<5} {s['name']:<3} "
                  f"ref_idc={s['ref']} {'IDR' if s['idr'] else ''}")

    # ── המסקנה ──────────────────────────────────────────────────────────
    print("\n  ── מה זה אומר ──")
    n_idr = sum(1 for s in slices if s["idr"])
    if n_idr:
        print(f"     יש {n_idr} IDR. כל מפענח יכול להתחיל.")
    elif i_frames and rec:
        print(f"     אין IDR, אבל יש {len(i_frames)} פריימי I ו-{rec} "
              "recovery point SEI.")
        print("     זה open-GOP עם נקודות התאוששות מסומנות: מפענח שמכבד")
        print("     recovery point יכול להתחיל, ומפענח שדורש IDR לא יכול.")
        print("     **זה ההסבר להבדל בין דפדפנים.**")
    elif i_frames:
        print(f"     אין IDR ואין recovery point, אבל יש {len(i_frames)} "
              "פריימי I.")
        print("     רק מפענח שמנסה להתחיל מ-I-slice שרירותי יצליח.")
    else:
        print("     אין IDR ואין אף פריים I בחלון שנבדק — אין שום נקודת")
        print("     כניסה, וגם מפענח סלחן יצטרך לחכות.")


if __name__ == "__main__":
    main()
