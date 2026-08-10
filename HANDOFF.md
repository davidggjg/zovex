# ZOVEX — מסמך העברה למתכנת

מסמך זה מרכז את כל מה שצריך כדי להמשיך לפתח ולתחזק את מערכת ZOVEX.
כל הקוד נמצא ב-Git (ראה "איפה כל הקוד" למטה).

> **סודות (חשוב):** אף סיסמה/טוקן לא נמצאים במסמך הזה או ב-Git. כולם יושבים
> בקובץ `.env` על השרת בלבד. את הערכים האמיתיים תעביר למתכנת בערוץ מאובטח
> (לא במייל רגיל / לא בצ'אט ציבורי).

---

## 1. סקירה — משלושה חלקים

| חלק | מה זה | איפה רץ |
|-----|-------|---------|
| **אתר** | React + Vite (Netflix-style), מקור האמת לתצוגה | GitHub Pages (`davidggjg.github.io/zovex`) + מוגש גם מה-VPS |
| **שרת (backend)** | FastAPI + Python. סטרימינג, פאנל ניהול, API, רלֵיי שידורים חיים | VPS (`zovex.duckdns.org`, IP 213.139.78.39) |
| **אפליקציית אנדרואיד** | React Native (WebView-based) | Repo נפרד: `davidggjg/zovex-android` |

**זרימת הווידאו:** התוכן יושב בערוצי טלגרם. השרת מריץ מאגר (pool) של בוטים
שמושכים את הקבצים מטלגרם ומזרימים אותם ל-HTTP (`/stream/...`) בזמן אמת, בלי
לשמור לדיסק. שידורים חיים עוברים דרך רלֵיי (`/hls-relay/...`).

---

## 2. איפה כל הקוד (Git)

Repo: **`github.com/davidggjg/zovex`**

| ענף | מה יש בו |
|-----|----------|
| `main` | האתר (React) |
| `claude/vps-bot-deploy` | **קוד השרת** (`vps-bot/`) — הגרסה העדכנית שרצה ב-production |
| `claude/zovex-home-refactor-c7bad4` | סקריפט תיקון סלאגים (`apply_slugs.py`) |

אפליקציה: **`github.com/davidggjg/zovex-android`** (ענף `main`).

לשכפול:
```
git clone https://github.com/davidggjg/zovex.git
git checkout claude/vps-bot-deploy   # לקוד השרת
```

---

## 3. קבצי השרת (`vps-bot/`)

| קובץ | תפקיד |
|------|-------|
| `main.py` | **הליבה** — כל ה-API, הסטרימינג, מאגר הבוטים, הרלֵיי, הייבוא (~3950 שורות) |
| `admin.html` | פאנל הניהול (מוגש מ-`/admin`) |
| `gen_sitemap.py` | יוצר `sitemap.xml` + `robots.txt` מהתוכן |
| `gen_session.py` | יוצר session strings לבוטים (Pyrogram) |
| `migrate_to_channel.py` | מיגרציית תוכן ישן לערוץ טלגרם |
| `verify_multibot.py` | בדיקת תקינות מאגר הבוטים |
| `harden.sh` / `https.sh` / `site.sh` | סקריפטי התקנה/הקשחה/HTTPS |

הקוד פורס ל-`/opt/zovex-bot/` על השרת. הנתונים ב-`/opt/zovex-bot/data/`.

---

## 4. הרצה (systemd + nginx)

- **שירות:** `zovex-bot` (systemd), מאזין על `PORT` (ברירת מחדל 8000).
  - `sudo systemctl restart zovex-bot` / `status` / `journalctl -u zovex-bot -f`
- **nginx** מול העולם (HTTPS), מעביר ל-`127.0.0.1:8000`.
  - ⚠️ nginx מעביר לשרת רק קידומות מסוימות: `/api`, `/app`, `/panel`, `/feedback`,
    `/pool`, `/content`, `/stream`, `/hls-relay`, `/uploads`, `/channels`, `/import`,
    `/admin`, `/movies.json`, `/ping`. נתיב חדש שלא בקידומת מוכרת יחזיר 405 מ-nginx —
    לשים לב כשמוסיפים endpoint.

---

## 5. משתני סביבה (`.env` על השרת — שמות בלבד)

```
PORT                    # פורט האזנה (8000)
PANEL_PASSWORD          # סיסמת פאנל הניהול
STREAM_CHANNEL_ID       # מזהה ערוץ טלגרם של התוכן
UPLOAD_BOT_TOKEN        # טוקן בוט ההעלאה (מנהלים שולחים לו קבצים)
TMDB_API_KEY            # לזיהוי אוטומטי של סרטים/סדרות
STREAM_PUBLIC_BASE      # הכתובת הציבורית (https://zovex.duckdns.org)
BASE_URL                # בסיס לקישורים
STREAM_SIGN_SECRET      # סוד לחתימת קישורי סטרימינג (HMAC)
STREAM_SIGN_TTL         # תוקף קישור חתום (שניות)
STREAM_PARALLEL_PARTS   # כמה חלקים במקביל לכל סטרים (הועלה ל-4 לביצועים)
STREAM_PARALLEL_WINDOW  # גודל חלון הזרמה מקבילה
DATA_DIR                # תיקיית הנתונים (/opt/zovex-bot/data)
HOTLINK_REFERERS        # הגנת hotlink — דומיינים מורשים
# ועוד (ראה os.environ.get ב-main.py): CHANNEL_MAX_MESSAGES, POOL_START_DELAY,
# NUM_DOWNLOAD_WORKERS, HF_TOKEN, DATA_REPO_ID, RESTART_KEY וכו'.
```

מאגר הבוטים (11 בוטים + userbot) מנוהל דרך הפאנל (`/pool/*`) ונשמר בקובץ נתונים.

---

## 6. קבצי נתונים (`/opt/zovex-bot/data/`)

| קובץ | תוכן |
|------|------|
| `content.json` | **מקור האמת** — כל הספרייה (~10,000 פריטים) |
| `content_version.txt` | מונה גרסה (optimistic lock לשמירה) |
| `content_backups/` | 30 גיבויים אחרונים אוטומטיים |
| `progress.json` / `history.json` | התקדמות והיסטוריית צפייה למשתמש |
| `admins.json` | מזהי טלגרם של מנהלים מורשים |
| `feedback.json` | הודעות תמיכה |
| `app_version.json` | גרסת אפליקציה + קישור עדכון |
| `relay_hosts.json` | allowlist של שרתי מקור מותרים לרלֵיי |
| `sign_secret.txt` | סוד חתימה (נוצר אוטומטית) |
| `zovex-latest.apk` | מטמון ה-APK שמוגש מ-`/app/apk` |

---

## 7. נקודות קצה עיקריות (API)

**תוכן:** `GET /content` · `POST /content/save` (password+base_version) · `GET /movies.json`
**סטרימינג:** `GET /stream/{chat_id}/{msg_id}` (חתום) · `GET /cast/...` · `GET /hls-relay/{host}/{path}`
**פאנל:** `POST /panel/api` · `POST /pool/*` · `POST /channels/*` · `POST /import/*` · `POST /uploads/*`
**שידורים חיים (רלֵיי):** `POST /api/relay/hosts` (list/add/remove)
**אפליקציה:** `GET /app/version` · `GET /app/apk` · `POST /app/apk/refresh` · `POST /app/version/set`
**סטטיסטיקות:** `POST /api/stats/summary`
**משוב/היסטוריה:** `POST /feedback/*` · `GET/POST /api/history` · `GET/POST /api/progress`

כל נקודות ה-POST הניהוליות דורשות `password` (ה-`PANEL_PASSWORD`), עם הגנת
brute-force והשוואת זמן-קבוע (`hmac.compare_digest`).

---

## 8. ארכיטקטורת הסטרימינג (החלק המורכב)

- **מאגר בוטים** (`_stream_bots`): 11 בוטים + userbot, כולם חברים בערוצי התוכן.
  `pick_stream_bot()` בוחר round-robin מבין הבריאים; בוט שנחנק (FloodWait) מסומן
  ב-cooldown ומדולג.
- **הזרמה מקבילה** (`channel_stream_range_parallel`): כל "חלון" מהסרט מפוצל
  למספר תת-טווחים שנמשכים במקביל דרך בוטים שונים → פי כמה מהירות.
  יש "רמפת האצה": חלון ראשון קטן (1MB) לזמן-התחלה מהיר, ואז גדל.
- **מטמון הודעה פר-בוט** (`_bot_msg_cache`): file_reference תקף רק בהקשר הבוט
  ששלף אותו, לכן כל בוט מחזיק cache משלו (TTL 15 דק', עם פינוי מעל 4000 רשומות).
- **קישורים חתומים:** `/stream` דורש `exp`+`sig` (HMAC) בתוקף.
- **רלֵיי שידורים חיים:** מושך מהמקור (HTTP), משכתב את ה-manifest לכתובות
  יחסיות דרך השרת, ומזרים סגמנטים. `HLS_RELAY_ALLOWED_HOSTS` = allowlist מנוהל.

---

## 9. משימות פתוחות / מומלצות

1. **228 סרטים בלי slug אנגלי** — `apply_slugs.py` (בענף `claude/zovex-home-refactor-c7bad4`)
   מוסיף custom_slug לכל אחד לפי id. מוכן להרצה.
2. **קאשינג לאתר** — הפרונט מוסיף `?t=Date.now()` לכל בקשת `/content` ואין
   `Cache-Control`, כך שכל כניסה מורידה מחדש ~1MB. הוספת ETag/Cache-Control
   ושימוש ב-`X-Content-Version` במקום cache-buster ישפרו מאוד זמני טעינה.
3. **sitemap לא מעודכן** — יש 968 עמודים אפשריים אבל בקובץ 328. להריץ
   `gen_sitemap.py` בתזמון (cron) ולוודא ש-`robots.txt` מצביע לדומיין הנכון.
4. **גיבוי content** — 30 × ~10MB = ~300MB. לשקול דחיסה (gzip) של הגיבויים.
5. **SEO** — אין תגית canonical; תוכן כפול בין github.io ל-duckdns.

---

## 10. אפליקציית אנדרואיד (`zovex-android`)

- React Native, מבוססת WebView. נבנית ב-GitHub Actions (`build-apk.yml`),
  מפרסמת release בשם `latest` עם `zovex.apk`.
- גרסה נוכחית: `versionName 1.0.4` (`versionCode 6`).
- עדכון-בתוך-האפליקציה: `UpdateDialog` מוריד את ה-APK מ-`/app/apk` (הדומיין שלך),
  מתקין דרך `ApkInstaller` (מודול Kotlin, FileProvider). דורש הרשאת
  `REQUEST_INSTALL_PACKAGES`.
- טופל: קריסות במכשירים בלי Google Play Services (Qin/טלוויזיות) — גייטינג של
  Google Cast + FCM, וגיארד ל-Picture-in-Picture.
- `APP_VERSION` ב-`src/api/movies.js` **חייב** להתאים ל-`versionName` ב-`build.gradle`,
  ולקרוא ל-`POST /app/version/set` בשרת אחרי כל release.
