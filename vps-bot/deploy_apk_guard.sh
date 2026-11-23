#!/bin/bash
# ZOVEX · תיקון נעילת העדכון: קישור APK נכון, אימות שהקובץ באמת APK, ולידציית גרסאות.
#   sudo bash deploy_apk_guard.sh      ·   sudo bash deploy_apk_guard.sh --rollback
set -u
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
DIR=/opt/zovex-bot; PY="$DIR/venv/bin/python"; [ -x "$PY" ] || PY=python3
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
die(){ echo "❌ $*"; exit 1; }
curl -fsSL "https://raw.githubusercontent.com/davidggjg/zovex/$REF/vps-bot/fix_apk_guard.py" -o $T/f.py || die "הורדה נכשלה"
if [ "${1:-}" = "--rollback" ]; then MAIN_PY=$DIR/main.py python3 $T/f.py --revert; systemctl restart zovex-bot; exit 0; fi
cp $DIR/main.py $T/main.before
MAIN_PY=$DIR/main.py python3 $T/f.py || die "התיקון לא הוחל (לא שונה כלום)"
"$PY" -m py_compile $DIR/main.py || { cp $T/main.before $DIR/main.py; die "שגיאת תחביר — שוחזר"; }
systemctl restart zovex-bot
ok=0; for i in $(seq 1 20); do sleep 2; curl -fsS -m 5 -o /dev/null http://127.0.0.1:8000/app/version && { ok=1; break; }; done
[ $ok = 1 ] || { cp $T/main.before $DIR/main.py; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
echo "✅ מותקן. מתקן את הקישור השמור ומרענן את ה-APK…"
PW=$(grep -E '^PANEL_PASSWORD=' $DIR/.env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"'\r')
[ -n "$PW" ] || { echo "⚠ לא נמצאה סיסמה ב-.env — בפאנל: שמור את קישור העדכון ולחץ 'רענן APK'"; exit 0; }
J=$(PW="$PW" python3 -c 'import json,os;print(json.dumps({"password":os.environ["PW"],"url":"https://github.com/davidggjg/zovex-android/releases/latest/download/zovex.apk"}))')
curl -s -m 20 -X POST http://127.0.0.1:8000/app/version/set -H 'Content-Type: application/json' -d "$J" >/dev/null
J2=$(PW="$PW" python3 -c 'import json,os;print(json.dumps({"password":os.environ["PW"]}))')
curl -s -m 20 -X POST http://127.0.0.1:8000/app/apk/refresh -H 'Content-Type: application/json' -d "$J2" >/dev/null
for i in $(seq 1 36); do sleep 5
  R=$(curl -s -m 10 -X POST http://127.0.0.1:8000/app/apk/status -H 'Content-Type: application/json' -d "$J2")
  echo "$R" | grep -q '"ok": *true\|"ok":true' && break
  echo "$R" | grep -q '"ok": *false\|"ok":false' && break
done
echo "$R" | python3 -c 'import json,sys
d=json.load(sys.stdin); l=d.get("last_refresh",{})
print("מקור:", d.get("source")); print("במטמון: %s MB, עודכן %s" % (d.get("size_mb"), d.get("updated")))
print("✅ הרענון הצליח — ה-APK החדש מוגש" if l.get("ok") else "❌ הרענון נכשל: %s" % l.get("error") if l.get("ok") is False else "⏳ עדיין מוריד — בדוק שוב בפאנל בעוד דקה")'
echo "השווה לגודל בגיטהאב (~68MB). רק אחרי זה לעדכן latest/min בפאנל."
