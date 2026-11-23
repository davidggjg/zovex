# ZOVEX · פרוטוקול אימות אפליקציות (zv-auth v1)

בסיס: https://zovex.duckdns.org

## 1. הנתיבים המוגנים
כל אחד מהנתיבים האלה חייב חתימה:
- כל `GET /content…`, חוץ מ-mutate, save ו-relink
- `/feedback/send`
- `/feedback/mine`
- `/api/progress…`
- `/api/history…`
- `/api/favorites…`
- `/api/refresh-stream`

נתיבי הווידאו (`/stream`, `/hls…`) לא משתנים. החתימה שלהם (exp/sig) נשארת כמו שהיא.

## 2. לחיצת יד: `POST /auth/session`
1. מייצרים זוג מפתחות **ECDH P-256**. המפתח הפרטי נשמר בצורה מאובטחת ולא יוצא מהמכשיר.
2. `pub` = המפתח הציבורי בפורמט raw uncompressed (65 בתים, מתחיל ב-0x04), מקודד ב-base64url בלי `=`.
3. גוף הבקשה (JSON):
   ```json
   {"pub":"<pub>","plat":"android|pc","app_proof":"<hex>","integrity":"<token אופציונלי>"}
   ```
   - `app_proof` = HMAC-SHA256(key=APP_SECRET, msg=המחרוזת `pub` כפי שנשלחה), כ-hex באותיות קטנות.
   - `APP_SECRET` מגיע מהפאנל: 🛡 אבטחה ← סודות אפליקציה. כל פלטפורמה מקבלת סוד משלה.
   - `integrity` (אנדרואיד בלבד): טוקן Play Integrity (classic request) עם `nonce` = base64url(SHA256(utf8(pub))) בלי `=`.
4. התשובה: `{"sid":"...","spub":"<base64url 65 בתים>","exp":<unix שניות>,"att":"app|integrity|none"}`
5. גוזרים את מפתח הסשן:
   - `shared` = ECDH(המפתח הפרטי, spub). זו קואורדינטת x, ‏32 בתים.
   - `key` = HKDF-SHA256(ikm=shared, salt=utf8(sid), info=utf8("zovex-v1"), length=32).
6. שומרים את `{sid, exp, key}` בצורה מאובטחת:
   - אנדרואיד: Keystore או EncryptedSharedPreferences.
   - מחשב: safeStorage של Electron.

   הסשן תקף 24 שעות. כשנשארות פחות מ-2 דקות, עושים לחיצת יד חדשה.

## 3. חתימה על כל בקשה מוגנת
```
TS    = הזמן הנוכחי במילישניות (מחרוזת)
NONCE = 12 בתים אקראיים ב-base64url (בין 8 ל-64 תווים, חדש בכל בקשה)
MSG   = METHOD + "\n" + PATH_WITH_QUERY + "\n" + TS + "\n" + NONCE
SIG   = base64url(HMAC-SHA256(key, utf8(MSG)))   // בלי =
```
**לגבי PATH_WITH_QUERY:**
- זה הנתיב בדיוק כפי שהוא נשלח בבקשה, כולל קידוד אחוזים (percent-encoding), עם `?query` אם יש.
- לדוגמה: `/content/item/%D7%90?x=1`.

**כותרות:**
- `X-ZV-S: sid`
- `X-ZV-T: TS`
- `X-ZV-N: NONCE`
- `X-ZV-Sig: SIG`

**כללים:**
- השעון של המכשיר חייב להיות בטווח של ±120 שניות משעון השרת.
- אסור לחזור על nonce.

## 4. שגיאות
- **401 עם `{"zv":"reauth"}`:** מוחקים את הסשן, עושים לחיצת יד חדשה, ושולחים שוב את הבקשה פעם אחת.
- **403 עם `{"zv":"blocked"}`:** הסשן נחסם. מציגים הודעה, ולא מנסים שוב בלולאה.
- **429:** יותר מדי בקשות. מחכים לפני שמנסים שוב.

## 5. מגבלות לסשן לשעה
| סוג | מגבלה |
|---|---|
| קטלוג (`/content`, `/content/lite`, `/content/live`) | 120 |
| פריט | 1500 |
| הודעות תמיכה | 10 |
| קריאת תמיכה | 180 |
| התקדמות, היסטוריה ומועדפים | 2000 |

חריגה מהמגבלה חוסמת את הסשן. לכן **מטמון (cache) לקטלוג חובה**: לא מושכים אותו בכל מסך.

## 6. בדיקה מהירה של המימוש
| מצב | תוצאה צפויה |
|---|---|
| חתימה תקינה | 200 |
| אותן כותרות פעם שנייה | 401 (replay) |
| שינוי ב-path | 401 |

בפאנל, בטאב 🛡 אבטחה, הסשן מופיע תחת הפלטפורמה שלו עם האימות `app` או `integrity`.
