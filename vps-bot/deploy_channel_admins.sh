#!/bin/bash
# ZOVEX · zv-admins: בוטים שמנהלים בערוץ התוכן ולא מחוברים לפאנל (קריאה בלבד). --rollback להסרה.
set -u
REF="${ZOVEX_REF:-claude/telegram-bots-video-freezing-m8rk0n}"
DIR=/opt/zovex-bot; PY="$DIR/venv_k/bin/python"; [ -x "$PY" ] || PY="$DIR/venv/bin/python"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
die(){ echo "❌ $*"; exit 1; }
curl -fsSL "https://raw.githubusercontent.com/davidggjg/zovex/$REF/vps-bot/fix_channel_admins.py" -o $T/f.py || die "הורדה נכשלה"
if [ "${1:-}" = "--rollback" ]; then MAIN_PY=$DIR/main.py python3 $T/f.py --revert; systemctl restart zovex-bot; rm -f /usr/local/bin/zv-admins; exit 0; fi
cp $DIR/main.py $T/main.before
MAIN_PY=$DIR/main.py python3 $T/f.py || die "לא הוחל (לא שונה כלום)"
"$PY" -m py_compile $DIR/main.py || { cp $T/main.before $DIR/main.py; die "שגיאת תחביר — שוחזר"; }
systemctl restart zovex-bot
ok=0; for i in $(seq 1 45); do sleep 2; curl -fsS -m 5 -o /dev/null http://127.0.0.1:8000/app/version && { ok=1; break; }; done
[ $ok = 1 ] || { cp $T/main.before $DIR/main.py; systemctl restart zovex-bot; die "השרת לא עלה — שוחזר"; }
cat > /usr/local/bin/zv-admins <<'R'
#!/bin/bash
PW=$(grep -E "^PANEL_PASSWORD=" /opt/zovex-bot/.env | head -1 | cut -d= -f2- | tr -d "\"'\r")
J=$(PW="$PW" python3 -c 'import json,os;print(json.dumps({"password":os.environ["PW"]}))')
curl -s -m 120 -X POST http://127.0.0.1:8000/pool/channel-admins -H "Content-Type: application/json" -d "$J" | python3 -c '
import json,sys; d=json.load(sys.stdin)
if "channels" not in d: print("שגיאה:", d); sys.exit()
for c in d["channels"]:
    a=c["admins"]; print("\n=== ערוץ %s · %d מנהלים · %d בוטים ===" % (c["channel"], len(a), sum(x["is_bot"] for x in a)))
    if c["error"] and not a: print("  שגיאה:", c["error"]); continue
    nb=[x for x in a if x["status"]=="NOT_IN_PANEL" and x["is_bot"]]
    print("🔴 בוטים מנהלים שלא מחוברים לפאנל (%d):" % len(nb))
    for x in nb: print("   @%-30s id=%s  %s" % (x["username"] or "-", x["id"], x["name"]))
    hu=[x for x in a if not x["is_bot"]]
    print("👤 מנהלים אנשים (%d): %s" % (len(hu), ", ".join("@"+(x["username"] or str(x["id"])) for x in hu)))
pn=d["panel_not_admin"]
print("\n🟡 בוטים בפאנל שאינם מנהלים באף ערוץ (%d): %s" % (len(pn), ", ".join("%s(%s)" % (x["name"], x["who"]) for x in pn) or "אין"))
print("סה\"כ בוטים בפאנל:", d["panel_bots"])'
R
chmod +x /usr/local/bin/zv-admins
echo "✅ מותקן. מחכה 30ש שהבוטים יתחברו…"; sleep 30; zv-admins
