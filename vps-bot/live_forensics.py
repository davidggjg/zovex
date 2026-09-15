#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_forensics.py — דוגם את השרת לאורך זמן כדי לענות על שאלה אחת:
*מה מצטבר* בין "אחרי restart הכול טס" ל"אחרי הרבה זמן מתחיל להיתקע".

קריאה בלבד. אין restart, אין reload, אין כתיבה לאף קובץ של המערכת.
אפשר להריץ תוך כדי צפייה או תוך כדי העלאה לטלגרם — הוא רק קורא
מ-/proc ומ-localhost.

    python3 live_forensics.py                    # 20 דק', דגימה כל 30ש
    python3 live_forensics.py --minutes 120      # שעתיים
    python3 live_forensics.py --interval 60
    nohup python3 live_forensics.py --minutes 720 > /tmp/fx.log 2>&1 &

בסוף מודפסת טבלת מגמה: מה גדל, כמה, והאם באופן מונוטוני.
מדד שגדל מונוטונית לאורך שעות הוא דליפה. מדד שעולה ויורד הוא עומס.
זה כל ההבדל, ובלי מדידה לאורך זמן אי אפשר להבחין ביניהם.
"""
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path
from urllib.request import urlopen

PORT = int(os.environ.get("PORT", "8000"))
BASE = f"http://127.0.0.1:{PORT}"
# מונים מצטברים: אמורים רק לעלות. לסמן אותם "דליפה" זו אזעקת שווא.
MONOTONIC_OK = {"tasks_created_total"}
# מטמונים עם תקרה מוגדרת: גדילה עד התקרה היא התנהגות תקינה.
BOUNDED = {"hls_seg_cache_bytes": "hls_seg_cache_max_bytes"}
# רק מדדים שצריכים לחזור לקו הבסיס. גדילה מונוטונית בהם = חשד לדליפה.
# מדדי "עומס רגעי" (כמו hls_segment_inflight) לא נכללים — הם אמורים לנוע.
LEAK_KEYS = [
    "fd", "sockets", "threads", "rss_mb", "tasks_pending", "ffmpeg_procs",
    "media_sessions_pools", "media_sessions_total_conns", "media_sessions_locks",
    "bot_msg_cache", "peer_errors", "band_timeouts", "rate_buckets",
    "hls_manifest_cache", "hls_prefetching", "hls_fix", "auth_fails",
    "json_cache", "payload_locks", "saved_jobs", "saved_tasks",
    "relay_learned_hosts", "prewarm_seen", "edge_filling",
]


def main_pid() -> int:
    try:
        out = subprocess.run(
            ["systemctl", "show", "zovex-bot", "-p", "MainPID", "--value"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        if out.isdigit() and int(out) > 0:
            return int(out)
    except Exception:
        pass
    try:
        out = subprocess.run(["pgrep", "-f", "/opt/zovex-bot/main.py"],
                             capture_output=True, text=True, timeout=10).stdout.split()
        if out:
            return int(out[0])
    except Exception:
        pass
    sys.exit("לא מצאתי את התהליך של zovex-bot. השירות רץ?")


def proc_stats(pid: int) -> dict:
    """RSS, threads, FD, sockets, ו-CPU jiffies מצטברים."""
    d = {}
    try:
        st = Path(f"/proc/{pid}/status").read_text()
        m = re.search(r"VmRSS:\s+(\d+) kB", st)
        d["rss_mb"] = round(int(m.group(1)) / 1024, 1) if m else 0
        m = re.search(r"Threads:\s+(\d+)", st)
        d["threads"] = int(m.group(1)) if m else 0
    except Exception:
        d["rss_mb"] = d["threads"] = 0
    fd_dir = Path(f"/proc/{pid}/fd")
    try:
        fds = os.listdir(fd_dir)
        d["fd"] = len(fds)
        socks = 0
        for fd in fds:
            try:
                if os.readlink(fd_dir / fd).startswith("socket:"):
                    socks += 1
            except OSError:
                pass            # fd נסגר בין listdir ל-readlink. נורמלי.
        d["sockets"] = socks
    except Exception:
        d["fd"] = d["sockets"] = 0
    try:
        f = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        d["_cpu_jiffies"] = int(f[11]) + int(f[12])     # utime + stime
    except Exception:
        d["_cpu_jiffies"] = 0
    return d


def ffmpeg_count(pid: int) -> int:
    try:
        out = subprocess.run(["pgrep", "-c", "-P", str(pid), "-f", "ffmpeg"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        if out.isdigit():
            return int(out)
    except Exception:
        pass
    try:
        out = subprocess.run(["pgrep", "-c", "-f", "hls_fix"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return int(out) if out.isdigit() else 0
    except Exception:
        return 0


def endpoint(path: str) -> dict:
    """/debug/* אינם מועברים ב-nginx, אבל מ-localhost הם נגישים ישירות."""
    try:
        with urlopen(BASE + path, timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


def journal_since(seconds: int) -> dict:
    """קצב שגיאות בחלון האחרון. זול: סופר מחרוזות קבועות בלבד."""
    pats = {
        "err_handler_closed": "handler is closed",
        "err_window_gave_up": "מסיים את התשובה כדי",
        "err_subrange_slow": "לא סיפק בייטים תוך",
        "err_floodwait": "FloodWait",
        "err_ffmpeg_died": "הנגן יראה קפיצה במספור",
        "err_timeout": "TimeoutError",
    }
    out = dict.fromkeys(pats, 0)
    try:
        log = subprocess.run(
            ["journalctl", "-u", "zovex-bot", "--since", f"{seconds} seconds ago",
             "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=30).stdout
        for k, p in pats.items():
            out[k] = log.count(p)
    except Exception:
        pass
    return out


def sample(pid: int, interval: int, prev_cpu) -> dict:
    row = {"t": time.time()}
    row.update(proc_stats(pid))
    row["ffmpeg_procs"] = ffmpeg_count(pid)

    hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    if prev_cpu is not None and interval > 0:
        row["cpu_pct"] = round(
            (row["_cpu_jiffies"] - prev_cpu) / hz / interval * 100, 1)
    else:
        row["cpu_pct"] = 0.0

    caches = endpoint("/debug/caches")
    if "_error" in caches:
        row["_caches_error"] = caches["_error"]
    else:
        for k, v in caches.items():
            if isinstance(v, (int, float)):
                row[k] = v
    tasks = endpoint("/debug/tasks")
    row["tasks_pending"] = tasks.get("pending_tracked", -1)
    row["tasks_created_total"] = tasks.get("created_total", -1)

    row.update(journal_since(interval))
    return row


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def trend(rows, keys):
    """מסווג כל מדד: גדילה מונוטונית = דליפה, תנודה = עומס.
    מונים מצטברים ומטמונים חסומים מוחרגים — סימון שלהם כדליפה
    הוא אזעקת שווא שמסיטה את החקירה."""
    out = []
    for k in keys:
        vals = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
        if len(vals) < 3:
            continue
        first, last = vals[0], vals[-1]
        peak = max(vals)
        rises = sum(1 for a, b in zip(vals, vals[1:]) if b > a)
        falls = sum(1 for a, b in zip(vals, vals[1:]) if b < a)
        delta = round(last - first, 1)

        if k in MONOTONIC_OK:
            per_min = delta / max(1e-9, (rows[-1]["t"] - rows[0]["t"]) / 60)
            verdict = f"⚪ מונה מצטבר — {per_min:,.0f}/דקה"
        elif k in BOUNDED:
            cap = next((r.get(BOUNDED[k]) for r in reversed(rows)
                        if r.get(BOUNDED[k])), None)
            pct = f" ({last*100/cap:.0f}% מהתקרה)" if cap else ""
            verdict = f"⚪ מטמון עם תקרה{pct}"
        elif falls == 0 and rises >= max(2, len(vals) // 4):
            verdict = "🔴 עולה ולא יורד — חשד לדליפה"
        elif delta > 0 and last >= peak and rises > falls * 2:
            verdict = "🟠 מגמת עלייה"
        elif falls > 0 and rises > 0:
            verdict = "🟢 עולה ויורד (עומס, לא דליפה)"
        else:
            verdict = "🟢 יציב"
        out.append((k, _fmt(first), _fmt(last), _fmt(peak),
                    f"{delta:+g}", verdict))
    return out


def run() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=20)
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--out", default="/tmp/zovex_forensics.csv")
    a = ap.parse_args()

    pid = main_pid()
    n = max(2, int(a.minutes * 60 / a.interval))
    started = subprocess.run(
        ["systemctl", "show", "zovex-bot", "-p", "ActiveEnterTimestamp", "--value"],
        capture_output=True, text=True).stdout.strip()

    print(f"תהליך {pid} · רץ מאז {started}")
    print(f"{n} דגימות כל {a.interval}ש ≈ {a.minutes} דקות. CSV: {a.out}")
    print("קריאה בלבד — בטוח להריץ תוך כדי צפייה או העלאה.\n")

    rows, prev_cpu = [], None
    try:
        for i in range(n):
            if i:
                time.sleep(a.interval)
            if not Path(f"/proc/{pid}").exists():
                print("\n⚠ התהליך נעלם — השירות עשה restart. עוצר.")
                break
            r = sample(pid, a.interval if i else 0, prev_cpu)
            prev_cpu = r["_cpu_jiffies"]
            rows.append(r)
            print(f"[{i+1:>3}/{n}] "
                  f"RSS {r['rss_mb']:>7.1f}MB · CPU {r['cpu_pct']:>5.1f}% · "
                  f"FD {r['fd']:>4} · sock {r['sockets']:>4} · thr {r['threads']:>3} · "
                  f"tasks {r['tasks_pending']:>4} · ffmpeg {r['ffmpeg_procs']:>2} · "
                  f"mediaconn {r.get('media_sessions_total_conns', '?'):>3}",
                  flush=True)
    except KeyboardInterrupt:
        print("\nהופסק ידנית — מנתח את מה שנאסף.")

    if len(rows) < 3:
        sys.exit("\nפחות מ-3 דגימות, אין מה לנתח.")

    keys = sorted({k for r in rows for k in r
                   if not k.startswith("_") and k != "t"})
    try:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(",".join(["time"] + keys) + "\n")
            for r in rows:
                fh.write(",".join(
                    [time.strftime("%H:%M:%S", time.localtime(r["t"]))]
                    + [str(r.get(k, "")) for k in keys]) + "\n")
        print(f"\nנשמר: {a.out}  ({len(rows)} דגימות)")
    except Exception as e:
        print(f"\n⚠ שמירת CSV נכשלה: {e}")

    span = (rows[-1]["t"] - rows[0]["t"]) / 60
    print(f"\n{'='*74}\nמגמה על פני {span:.0f} דקות\n{'='*74}")
    print("{:<30}{:>11}{:>11}{:>11}{:>9}  {}".format(
        "מדד", "התחלה", "סוף", "שיא", "שינוי", "ניתוח"))
    print("-" * 74)

    leaks = [k for k in LEAK_KEYS if k in keys]
    rest = [k for k in keys if k not in leaks and not k.startswith("err_")]
    errs = [k for k in keys if k.startswith("err_")]

    flagged = []
    for group, label in ((leaks, "משאבים שאמורים לחזור לקו הבסיס"),
                         (rest, "מונים ועומס רגעי"),
                         (errs, "קצב שגיאות לחלון")):
        rt = trend(rows, group)
        if not rt:
            continue
        print(f"\n— {label}")
        for k, f, l, p, d, v in rt:
            print(f"{k:<30}{f:>11}{l:>11}{p:>11}{d:>9}  {v}")
            if v.startswith("🔴"):
                flagged.append(k)

    print(f"\n{'='*74}")
    if flagged:
        print("🔴 מדדים שעלו ולא ירדו אף פעם — אלה החשודים:")
        for k in flagged:
            print(f"     • {k}")
        print("\n   חשוב: בחלון של עשרים דקות גם דליפה אמיתית נראית כמו רעש.")
        print("   הרצה של 6-12 שעות היא זו שמכריעה:")
        print("     nohup python3 live_forensics.py --minutes 720 "
              "--interval 120 > /tmp/fx.log 2>&1 &")
    else:
        print("🟢 שום משאב לא עלה באופן מונוטוני בחלון הזה.")
        print("   זה לא מזכה — זה אומר שהחלון קצר מדי. הרץ 6-12 שעות.")
    print("שלח לי את הפלט הזה ואת ה-CSV.")


if __name__ == "__main__":
    run()
