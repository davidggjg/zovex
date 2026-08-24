"""מרפא בריכה מתה אחרי timeouts רצופים (מתקן 3.12 -> 0.14 MB/s).
הרצה:  sudo /opt/zovex-bot/venv/bin/python /opt/zovex-bot/patch_heal.py
"""
import py_compile, shutil, sys, time, pathlib
LIVE=pathlib.Path("/opt/zovex-bot/main.py")
PAIRS=[('timeout counter decl', 'def _is_dead_conn(err) -> bool:', '# מונה timeouts רצופים לכל (בוט, DC). מתאפס בכל הצלחה, כך שרק *רצף* אמיתי\n# נחשב לבריכה מתה — חלון איטי מזדמן לא מפיל כלום.\n_band_timeouts: dict = {}\nBAND_TIMEOUT_LIMIT = int(os.environ.get("STREAM_BAND_TIMEOUT_LIMIT", "2"))\n\n\ndef _is_dead_conn(err) -> bool:'), ('reset on success', '        _mark_ok(bot)\n        if elapsed > 0:', '        _mark_ok(bot)\n        _band_timeouts.pop((bot["name"], dc_id), None)   # חלון שהצליח מאפס את הרצף\n        if elapsed > 0:'), ('timeout handler', '    except asyncio.TimeoutError:\n        # החלון חרג מה-budget. איטי ≠ מת: הפלת הבריכה על כל timeout היא בדיוק\n        # ה-thrash שהקפיץ תקיעות כל כמה דקות. לא מפילים — נופלים לחלון הזה, ואם\n        # החיבור באמת מת החלון הבא ייכשל בשגיאת-חיבור וזו תפיל אותו נכון.\n        log.info("media bands (%s) חלון איטי (timeout) — fallback בלי הפלה", bot["name"])\n        note_bot_speed(bot, 0.0)\n        return None', '    except asyncio.TimeoutError:\n        # החלון חרג מה-budget. timeout בודד הוא איטיות ולא מוות, והפלת הבריכה\n        # על כל אחד כזה היא ה-thrash שהקפיץ תקיעות כל כמה דקות.\n        #\n        # אבל ההנחה הקודמת — "אם החיבור באמת מת, החלון הבא ייכשל בשגיאת חיבור\n        # וזו תפיל אותו" — פשוט אינה נכונה: חיבור MTProto מת *נתקע*, כלומר\n        # מתבטא כ-timeout ולא כשגיאה. לכן בריכה מתה לא התרפאתה לעולם, כל חלון\n        # עשה timeout, והכל נפל למסלול האיטי (נמדד 3.12MB/s → 0.14MB/s).\n        #\n        # הפשרה: סופרים timeouts רצופים לאותו (בוט, DC). בודד — מתעלמים; רצף\n        # קצר — זו כבר לא איטיות אלא בריכה מתה, ומפילים אותה כדי שתיבנה טרייה.\n        key = (bot["name"], dc_id)\n        n = _band_timeouts.get(key, 0) + 1\n        _band_timeouts[key] = n\n        note_bot_speed(bot, 0.0)\n        if n >= BAND_TIMEOUT_LIMIT and dc_id is not None and gen is not None:\n            log.warning("media bands (%s) %d timeouts רצופים — מרענן חיבורים",\n                        bot["name"], n)\n            _band_timeouts.pop(key, None)\n            await drop_media_sessions(bot["name"], dc_id, gen)\n        else:\n            log.info("media bands (%s) חלון איטי (timeout %d/%d)",\n                     bot["name"], n, BAND_TIMEOUT_LIMIT)\n        return None')]
def main():
    out=LIVE.read_text(encoding="utf-8"); ap,sk,ms=[],[],[]
    for name,old,new in PAIRS:
        if new in out: sk.append(name)
        elif old in out: out=out.replace(old,new,1); ap.append(name)
        else: ms.append(name)
    if ms:
        print("\u274c \u05e7\u05d8\u05e2\u05d9\u05dd \u05dc\u05d0 \u05e0\u05de\u05e6\u05d0\u05d5:")
        for m in ms: print("   -",m)
        print("\u05dc\u05d0 \u05e9\u05d5\u05e0\u05d4 \u05db\u05dc\u05d5\u05dd."); sys.exit(2)
    if not ap:
        print("\u2713 \u05db\u05d1\u05e8 \u05de\u05d5\u05d7\u05dc."); return
    bak=LIVE.with_name("main_before_heal_%d.py"%int(time.time()))
    shutil.copy2(LIVE,bak); LIVE.write_text(out,encoding="utf-8")
    try: py_compile.compile(str(LIVE),doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak,LIVE); print("\u274c \u05e7\u05d5\u05de\u05e4\u05d9\u05dc\u05e6\u05d9\u05d4 \u05e0\u05db\u05e9\u05dc\u05d4 \u2014 \u05e9\u05d5\u05d7\u05d6\u05e8. %s"%e); sys.exit(3)
    print("\u2705 \u05d4\u05d5\u05d7\u05dc. \u05e9\u05d5\u05e0\u05d5 %d \u05e7\u05d8\u05e2\u05d9\u05dd:"%len(ap))
    for a in ap: print("   +",a)
    print("\u05d2\u05d9\u05d1\u05d5\u05d9: %s"%bak.name)
    print("\n\u05e2\u05db\u05e9\u05d9\u05d5:  sudo systemctl restart zovex-bot")
if __name__=="__main__": main()
