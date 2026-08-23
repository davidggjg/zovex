#!/bin/bash
# מחיל את תיקון ה-streaming (מניעת thrash של בריכת החיבורים + טיפול FloodWait +
# תיקון קריסת סיסמה לא-ASCII) על /opt/zovex-bot/main.py.
# בטוח: גיבוי -> apply עם --forward (אידמפוטנטי) -> בדיקת קומפילציה -> שחזור בכשל.
set -u
LIVE=/opt/zovex-bot/main.py
PY=/opt/zovex-bot/venv/bin/python
TS=$(date +%s)
BAK="/opt/zovex-bot/main_before_streamfix_${TS}.py"
PATCHFILE="/tmp/streamfix_${TS}.patch"

cat > "$PATCHFILE" <<'PATCH_EOF'
diff --git a/main.py b/main.py
index 84cfa6f..4d167c4 100644
--- a/main.py
+++ b/main.py
@@ -1090,14 +1090,37 @@ MEDIA_BANDS_PER_MB = float(os.environ.get("STREAM_MEDIA_BANDS_PER_MB", "3"))
 MEDIA_BANDS_MAX = int(os.environ.get("STREAM_MEDIA_BANDS_MAX", "35"))
 
 
+# עד כמה זמן FloodWait כדאי "לרכוב" בתוך רצועה לפני ויתור. FloodWait קצר
+# (טלגרם מבקש להאט לרגע) עדיף לספוג מאשר להפיל את כל החלון; FloodWait ארוך
+# עדיף לזרוק — החלון ייפול אחורה למסלול אחר ולא יחזיק את הצופה תקוע.
+MEDIA_BAND_FLOOD_CAP = int(os.environ.get("STREAM_BAND_FLOOD_CAP", "8"))
+
+
+def _is_dead_conn(err) -> bool:
+    """האם השגיאה מעידה על *חיבור מת* (ואז כדאי להפיל ולבנות בריכה טרייה),
+    להבדיל מהאטה רגעית (FloodWait/timeout) שבה הבריכה בריאה. הפלת בריכה על
+    כל האטה גרמה ל-thrash מתמיד: כל כמה דקות כל החיבורים נהרסו ונבנו, והסרט
+    נתקע בזמן הבנייה."""
+    return isinstance(err, (ConnectionError, OSError, EOFError, RuntimeError))
+
+
 async def _band_fetch(session: Session, location, lo: int, hi: int) -> bytes:
     """מושך בדיוק [lo, hi] דרך חיבור media יחיד ומחזיר את הבייטים."""
     out = bytearray()
     offset = (lo // MEDIA_CHUNK) * MEDIA_CHUNK
     produced = offset
     while produced <= hi:
-        r = await session.invoke(functions.upload.GetFile(
-            location=location, offset=offset, limit=MEDIA_CHUNK, precise=False))
+        try:
+            r = await session.invoke(functions.upload.GetFile(
+                location=location, offset=offset, limit=MEDIA_CHUNK, precise=False))
+        except FloodWait as e:
+            # קריטי: הגרסה הקודמת לא תפסה FloodWait כאן כלל — כל האטה של טלגרם
+            # הפילה את הרצועה, ובעקבותיה נזרקה כל בריכת החיבורים (thrash) והסרט
+            # נתקע. FloodWait קצר: ישנים ומנסים שוב; ארוך: זורקים בשקט (fallback).
+            if e.value > MEDIA_BAND_FLOOD_CAP:
+                raise
+            await asyncio.sleep(e.value + 0.5)
+            continue
         chunk = getattr(r, "bytes", b"")
         if not chunk:
             break
@@ -1188,15 +1211,22 @@ async def _media_bands_fetch(chat_id, message_id, lo, hi):
         elapsed = time.time() - t_start
         bad = next((p for p in parts if not isinstance(p, (bytes, bytearray))), None)
         if bad is not None:
-            # שגיאה באחד החלקים — לא מגישים חלקי, ומרעננים את החיבורים
-            log.warning("media bands (%s) חלק נכשל: %s — מרענן חיבורים", bot["name"], bad)
-            await drop_media_sessions(bot["name"], dc_id, gen)
-            # קריטי: כאן ה-FileReferenceExpired מגיע *בתוך* תוצאות ה-gather
-            # (return_exceptions=True), ולכן ה-except למטה לא תופס אותו. בלי
-            # הניקוי הזה ה-reference הפג נשאר במטמון וכל חלון נכשל שוב → הסרט
-            # נתקע אחרי ~37 דק' עד כניסה מחדש. הניקוי מאלץ הודעה טרייה.
+            # לא מגישים חלון חלקי — נופלים למסלול אחר. *אבל* מפילים את בריכת
+            # החיבורים רק אם הכשל הוא חיבור מת. FloodWait/reference-פג הם רגעיים
+            # והבריכה בריאה; הפלה שלה עליהם גרמה ל-thrash והתקיעות "כל כמה דקות".
             if isinstance(bad, FileReferenceExpired):
+                # קריטי: FileReferenceExpired מגיע *בתוך* תוצאות ה-gather ולכן
+                # ה-except למטה לא תופס אותו. בלי הניקוי ה-reference הפג נשאר
+                # במטמון וכל חלון נכשל שוב → הסרט נתקע עד כניסה מחדש.
                 _purge_msg_cache(chat_id, message_id)
+            elif _is_dead_conn(bad):
+                log.warning("media bands (%s) חיבור מת: %s — מרענן חיבורים",
+                            bot["name"], type(bad).__name__)
+                await drop_media_sessions(bot["name"], dc_id, gen)
+            else:
+                # FloodWait ארוך או שגיאה רגעית אחרת — בריכה בריאה, לא נוגעים.
+                log.info("media bands (%s) חלון נכשל רגעית: %s — fallback",
+                         bot["name"], type(bad).__name__)
             return None
         out = bytearray()
         for p in parts:
@@ -1210,15 +1240,25 @@ async def _media_bands_fetch(chat_id, message_id, lo, hi):
     except FileReferenceExpired:
         _purge_msg_cache(chat_id, message_id)
         return None
+    except asyncio.TimeoutError:
+        # החלון חרג מה-budget. איטי ≠ מת: הפלת הבריכה על כל timeout היא בדיוק
+        # ה-thrash שהקפיץ תקיעות כל כמה דקות. לא מפילים — נופלים לחלון הזה, ואם
+        # החיבור באמת מת החלון הבא ייכשל בשגיאת-חיבור וזו תפיל אותו נכון.
+        log.info("media bands (%s) חלון איטי (timeout) — fallback בלי הפלה", bot["name"])
+        note_bot_speed(bot, 0.0)
+        return None
+    except FloodWait as e:
+        log.info("media bands (%s) FloodWait %ss — fallback בלי הפלה", bot["name"], e.value)
+        return None
     except Exception as e:
         # שם הטיפוס חובה: str(asyncio.TimeoutError()) ריק, והשורה הזו הודפסה
         # כ"נכשל: " בלי סיבה — מה שהסתיר בדיוק את הכשל הנפוץ ביותר כאן.
         log.warning("media bands (%s) נכשל: %s: %s — נופל למסלול הבוטים",
                     bot["name"], type(e).__name__, e)
         note_bot_speed(bot, 0.0)      # כשל מוריד את הציון מיד
-        # gen=None פירושו שהכשל קרה עוד לפני שקיבלנו בריכה — אין מה להפיל,
-        # ובוודאי לא את הבריכה של מישהו אחר.
-        if dc_id is not None and gen is not None:
+        # gen=None פירושו שהכשל קרה עוד לפני שקיבלנו בריכה — אין מה להפיל.
+        # מפילים רק על חיבור מת ממש (לא על שגיאה רגעית) כדי לא ליצור thrash.
+        if dc_id is not None and gen is not None and _is_dead_conn(e):
             await drop_media_sessions(bot["name"], dc_id, gen)
         return None
 
@@ -2136,9 +2176,13 @@ def panel_role(request: Request, password: str) -> str:
         raise HTTPException(status_code=429, detail="יותר מדי ניסיונות — נסה שוב בעוד כמה דקות")
     pw = password or ""
     role = None
-    if PANEL_PASSWORD and hmac.compare_digest(pw, PANEL_PASSWORD):
+    # השוואה על bytes ולא על str: hmac.compare_digest על מחרוזת עם תווים
+    # לא-ASCII (סיסמה בעברית וכו') זורק TypeError ומפיל את ה-handler במקום
+    # להחזיר "שגוי" — מה שהחזיר תשובה ריקה לכל בקשה עם סיסמה כזו.
+    pw_b = pw.encode("utf-8", "surrogatepass")
+    if PANEL_PASSWORD and hmac.compare_digest(pw_b, PANEL_PASSWORD.encode("utf-8", "surrogatepass")):
         role = "admin"
-    elif EDITOR_PASSWORD and hmac.compare_digest(pw, EDITOR_PASSWORD):
+    elif EDITOR_PASSWORD and hmac.compare_digest(pw_b, EDITOR_PASSWORD.encode("utf-8", "surrogatepass")):
         role = "editor"
     if role is None:
         fails.append(now)
PATCH_EOF

cd /opt/zovex-bot || { echo "❌ אין /opt/zovex-bot"; exit 1; }

if patch -p1 --reverse --dry-run -f < "$PATCHFILE" >/dev/null 2>&1; then
  echo "✓ התיקון כבר מוחל — אין מה לעשות."
  rm -f "$PATCHFILE"; exit 0
fi
if ! patch -p1 --forward --dry-run -f < "$PATCHFILE" >/dev/null 2>&1; then
  echo "❌ ה-patch לא מתאים לקובץ החי (אולי שונה ידנית). לא שוניתי כלום."
  rm -f "$PATCHFILE"; exit 2
fi

cp "$LIVE" "$BAK"
patch -p1 --forward -f < "$PATCHFILE" >/dev/null
if "$PY" -c "import ast; ast.parse(open('$LIVE').read())" 2>/dev/null; then
  echo "✅ הוחל בהצלחה. גיבוי: $BAK"
  echo "עכשיו:  sudo systemctl restart zovex-bot"
else
  cp "$BAK" "$LIVE"
  echo "❌ קומפילציה נכשלה — שוחזר הגיבוי. לא בוצע שינוי."
  rm -f "$PATCHFILE"; exit 3
fi
rm -f "$PATCHFILE"
