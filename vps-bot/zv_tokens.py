# -*- coding: utf-8 -*-
"""zv_tokens — אימות לקוחות (אתר / אנדרואיד / מחשב) בסגנון Netflix MSL.

זרימה:
  1. הלקוח מייצר זוג מפתחות ECDH P-256 שהמפתח הפרטי שלו לא ניתן לייצוא
     (WebCrypto non-extractable / Android Keystore), ושולח את הציבורי
     ל-POST /api/auth/session יחד עם הוכחת-אמינות:
        web     → Cloudflare Turnstile (בדיקת רובוט בלתי נראית)
        android → Google Play Integrity (האפליקציה המקורית, מכשיר אמיתי)
        pc/any  → app_proof = HMAC(סוד-אפליקציה, המפתח הציבורי)
  2. השרת מחזיר sid + מפתח ציבורי זמני; שני הצדדים גוזרים (ECDH+HKDF)
     מפתח HMAC משותף שלא עובר ברשת. הסשן תקף 24 שעות.
  3. כל בקשה מוגנת נחתמת: HMAC(מפתח, METHOD\\nPATH\\nTS\\nNONCE).
     חותמת זמן ±120ש' + nonce חד-פעמי ⇒ אין שכפול/הקלטה. טוקן גנוב בלי
     המפתח הפרטי של המכשיר — חסר ערך.
  4. מנוע התנהגות לכל סשן (משיכת קטלוג חוזרת, ספאם בתמיכה) ⇒ חסימה.
  5. מצב: off / monitor (רק רושם) / enforce (חוסם). נשלט מהפאנל.
"""
import base64, hashlib, hmac, json, os, secrets, time, threading
from typing import Optional

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from cryptography.hazmat.primitives.asymmetric import ec, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

DIR = os.environ.get("ZV_TOKENS_DIR", os.path.dirname(os.path.abspath(__file__)))
CFG_FILE = os.path.join(DIR, "zv_tokens_cfg.json")
SES_FILE = os.path.join(DIR, "zv_sessions.json")

SESSION_TTL = 24 * 3600
# חלון שעון: קופסאות Android TV בלי RTC סוטות דקות. הגנת replay נשענת על ה-nonce
# (נשמר 2×SKEW), לא על צרות החלון.
SKEW = int(os.environ.get("ZV_SKEW", "900"))
NONCE_MAX = int(os.environ.get("ZV_NONCE_MAX", "1000000"))
PLATS = ("web", "android", "pc")
ATT_RANK = {"none": 0, "app": 1, "turnstile": 2, "integrity": 3}

# מגבלות התנהגות לסשן לשעה. חריגה ⇒ חסימת הסשן.
RULES = {"catalog": 120, "item": 1500, "fb_send": 10, "fb_read": 180, "user": 2000, "refresh": 600}
HANDSHAKE_PER_IP_HOUR = int(os.environ.get("ZV_HANDSHAKE_PER_IP", "60"))

_lock = threading.Lock()


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _ub64(s: str) -> bytes:
    s = s.strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _default_cfg():
    return {
        "mode": "monitor",
        "require": {"web": "turnstile", "android": "integrity", "pc": "app"},
        "app_secrets": {"android": secrets.token_urlsafe(32), "pc": secrets.token_urlsafe(32)},
        "turnstile_sitekey": os.environ.get("TURNSTILE_SITEKEY", ""),
        "turnstile_secret": os.environ.get("TURNSTILE_SECRET", ""),
        "android_package": os.environ.get("PLAY_INTEGRITY_PACKAGE", ""),
        "play_sa_json": os.environ.get("PLAY_INTEGRITY_SA_FILE", ""),
    }


CFG = _load(CFG_FILE, None)
if not CFG:
    CFG = _default_cfg()
    _save(CFG_FILE, CFG)
for _k, _v in _default_cfg().items():
    CFG.setdefault(_k, _v)

SES: dict = _load(SES_FILE, {})
_dirty = False
_last_save = 0.0
_nonces: dict = {}
_hs_ip: dict = {}
STATS = {"ok": 0, "no_token": 0, "bad_sig": 0, "expired": 0, "blocked": 0, "replay": 0,
         "since": time.time(), "by_plat": {}}


def _persist(force=False):
    global _dirty, _last_save
    now = time.time()
    if not force and (not _dirty or now - _last_save < 30):
        return
    with _lock:
        for sid in [s for s, v in SES.items() if v.get("exp", 0) < now - 3600]:
            SES.pop(sid, None)
        if len(SES) > 200000:
            for sid in sorted(SES, key=lambda s: SES[s].get("last", 0))[:len(SES) - 200000]:
                SES.pop(sid, None)
        try:
            _save(SES_FILE, SES)
        except Exception:
            pass
        _dirty = False
        _last_save = now


def _plat_bump(plat, key):
    d = STATS["by_plat"].setdefault(plat or "?", {})
    d[key] = d.get(key, 0) + 1


# ── הוכחות אמינות ────────────────────────────────────────────────────────────
async def _verify_turnstile(token: str, ip: str) -> bool:
    sec = CFG.get("turnstile_secret")
    if not sec or not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                             data={"secret": sec, "response": token, "remoteip": ip})
            return bool(r.json().get("success"))
    except Exception:
        return False


_g_tok = {"t": "", "exp": 0}


async def _google_access_token() -> Optional[str]:
    if _g_tok["t"] and _g_tok["exp"] > time.time() + 60:
        return _g_tok["t"]
    path = CFG.get("play_sa_json")
    if not path or not os.path.exists(path):
        return None
    sa = _load(path, {})
    now = int(time.time())
    head = _b64u(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claim = _b64u(json.dumps({"iss": sa["client_email"], "aud": "https://oauth2.googleapis.com/token",
                              "scope": "https://www.googleapis.com/auth/playintegrity",
                              "iat": now, "exp": now + 3600}).encode())
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = key.sign(f"{head}.{claim}".encode(), padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{head}.{claim}.{_b64u(sig)}"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post("https://oauth2.googleapis.com/token",
                         data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt})
        d = r.json()
    _g_tok.update(t=d.get("access_token", ""), exp=time.time() + int(d.get("expires_in", 0)))
    return _g_tok["t"] or None


async def _verify_integrity(token: str, pub_b64: str) -> bool:
    pkg = CFG.get("android_package")
    if not pkg or not token:
        return False
    try:
        at = await _google_access_token()
        if not at:
            return False
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"https://playintegrity.googleapis.com/v1/{pkg}:decodeIntegrityToken",
                             headers={"Authorization": f"Bearer {at}"}, json={"integrity_token": token})
        p = r.json().get("tokenPayloadExternal", {})
        req = p.get("requestDetails", {})
        want = _b64u(hashlib.sha256(pub_b64.encode()).digest())
        if req.get("requestPackageName") != pkg:
            return False
        if req.get("nonce", "").rstrip("=") != want and req.get("requestHash", "").rstrip("=") != want:
            return False
        if abs(int(req.get("timestampMillis", "0")) / 1000 - time.time()) > 600:
            return False
        if p.get("appIntegrity", {}).get("appRecognitionVerdict") != "PLAY_RECOGNIZED":
            return False
        dev = p.get("deviceIntegrity", {}).get("deviceRecognitionVerdict", [])
        return "MEETS_DEVICE_INTEGRITY" in dev or "MEETS_STRONG_INTEGRITY" in dev
    except Exception:
        return False


def _verify_app(plat: str, proof: str, pub_b64: str) -> bool:
    sec = (CFG.get("app_secrets") or {}).get(plat)
    if not sec or not proof:
        return False
    want = hmac.new(sec.encode(), pub_b64.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, proof.lower())


# ── סיווג נתיבים ─────────────────────────────────────────────────────────────
_ADMIN_CONTENT = ("/content/mutate", "/content/save", "/content/relink")


def classify(method: str, path: str) -> Optional[str]:
    if path.startswith("/content"):
        if path in _ADMIN_CONTENT or method != "GET":
            return None
        if path in ("/content", "/content/lite", "/content/live"):
            return "catalog"
        return "item"
    if path == "/feedback/send":
        return "fb_send"
    if path == "/feedback/mine":
        return "fb_read"
    if path.startswith(("/api/progress", "/api/history", "/api/favorites")):
        return "user"
    if path == "/api/refresh-stream":
        return "refresh"
    return None


def _bump_rule(s: dict, bucket: str) -> bool:
    hour = int(time.time() // 3600)
    h = s.setdefault("h", {})
    cur = h.get(bucket)
    if not cur or cur[0] != hour:
        cur = [hour, 0]
    cur[1] += 1
    h[bucket] = cur
    s["n"] = s.get("n", 0) + 1
    return cur[1] <= RULES.get(bucket, 10**9)


def _check_sig(scope, headers) -> tuple:
    """מחזיר (סטטוס, sid, session)."""
    sid = headers.get("x-zv-s")
    if not sid:
        return "no_token", None, None
    s = SES.get(sid)
    if not s:
        return "expired", sid, None
    now = time.time()
    if s.get("exp", 0) < now:
        return "expired", sid, s
    try:
        ts = int(headers.get("x-zv-t", "0")) / 1000.0
    except ValueError:
        return "bad_sig", sid, s
    if abs(ts - now) > SKEW:
        return "expired", sid, s
    nonce = headers.get("x-zv-n", "")
    sig = headers.get("x-zv-sig", "")
    if not (8 <= len(nonce) <= 64) or not sig:
        return "bad_sig", sid, s
    method = scope.get("method", "GET")
    qs = scope.get("query_string", b"").decode("latin-1")
    raw = scope.get("raw_path") or scope.get("path", "").encode()
    cands = [raw.decode("latin-1"), scope.get("path", "")]
    key = bytes.fromhex(s["k"])
    ok = False
    for p in cands:
        full = p + ("?" + qs if qs else "")
        want = hmac.new(key, f"{method}\n{full}\n{headers.get('x-zv-t')}\n{nonce}".encode("utf-8"),
                        hashlib.sha256).digest()
        try:
            if hmac.compare_digest(want, _ub64(sig)):
                ok = True
                break
        except Exception:
            break
    if not ok:
        return "bad_sig", sid, s
    nk = sid + ":" + nonce
    if nk in _nonces:
        return "replay", sid, s
    _nonces[nk] = now + SKEW * 2
    if len(_nonces) > NONCE_MAX:
        for k in [k for k, e in _nonces.items() if e < now]:
            _nonces.pop(k, None)
        if len(_nonces) > NONCE_MAX:          # עדיין מלא: דוחים בקשות חדשות עד שיתפנה
            _nonces.pop(nk, None)
            return "replay", sid, s
    return "ok", sid, s


class _TokenASGI:
    def __init__(self, app, is_local):
        self.app = app
        self.is_local = is_local

    async def __call__(self, scope, receive, send):
        global _dirty
        if scope.get("type") != "http" or CFG.get("mode") == "off":
            return await self.app(scope, receive, send)
        bucket = classify(scope.get("method", ""), scope.get("path", ""))
        if bucket is None:
            return await self.app(scope, receive, send)
        request = Request(scope)
        if self.is_local(request):
            return await self.app(scope, receive, send)
        st, sid, s = _check_sig(scope, request.headers)
        plat = (s or {}).get("plat")
        if st == "ok" and s.get("blocked"):
            st = "blocked"
        if st == "ok":
            s["last"] = time.time()
            if not _bump_rule(s, bucket):
                s["blocked"] = f"חריגה: {bucket} מעל {RULES.get(bucket)} לשעה"
                s["blocked_at"] = time.time()
                st = "blocked"
            _dirty = True
        STATS[st] = STATS.get(st, 0) + 1
        _plat_bump(plat, st)
        _persist()
        if st != "ok" and CFG.get("mode") == "enforce":
            code = 403 if st == "blocked" else 401
            resp = JSONResponse({"detail": "נדרש אימות אפליקציה" if code == 401 else "הגישה נחסמה",
                                 "zv": "reauth" if code == 401 else "blocked",
                                 "server_time": int(time.time() * 1000), "reason": st},
                                status_code=code, headers={"X-ZV-Time": str(int(time.time() * 1000))})
            return await resp(scope, receive, send)
        return await self.app(scope, receive, send)


class SessionReq(BaseModel):
    pub: str
    plat: str = "web"
    turnstile: Optional[str] = ""
    integrity: Optional[str] = ""
    app_proof: Optional[str] = ""


class AdminReq(BaseModel):
    password: str
    mode: Optional[str] = None
    require: Optional[dict] = None
    rotate: Optional[str] = None
    sid: Optional[str] = None
    unblock: Optional[bool] = False
    turnstile_sitekey: Optional[str] = None
    turnstile_secret: Optional[str] = None
    android_package: Optional[str] = None


def install(api, check_panel_password, client_ip, is_local):
    api.add_middleware(_TokenASGI, is_local=is_local)

    @api.get("/api/auth/config")
    async def auth_config():
        return {"mode": CFG.get("mode"), "turnstile_sitekey": CFG.get("turnstile_sitekey", ""),
                "ttl": SESSION_TTL}

    @api.post("/api/auth/session")
    async def auth_session(req: SessionReq, request: Request):
        global _dirty
        ip = client_ip(request)
        now = time.time()
        lst = [t for t in _hs_ip.get(ip, []) if now - t < 3600]
        if len(lst) >= HANDSHAKE_PER_IP_HOUR:
            raise HTTPException(status_code=429, detail="יותר מדי חיבורים — נסה שוב מאוחר יותר")
        lst.append(now)
        _hs_ip[ip] = lst
        if len(_hs_ip) > 50000:
            _hs_ip.clear()
        plat = req.plat if req.plat in PLATS else "web"
        try:
            raw = _ub64(req.pub)
            if len(raw) != 65:
                raise ValueError
            cpub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
        except Exception:
            raise HTTPException(status_code=400, detail="מפתח לא תקין")
        pub_b64 = _b64u(raw)
        att = "none"
        if plat == "android" and await _verify_integrity(req.integrity or "", pub_b64):
            att = "integrity"
        elif plat == "web" and await _verify_turnstile(req.turnstile or "", ip):
            att = "turnstile"
        if att == "none" and plat in ("android", "pc") and _verify_app(plat, req.app_proof or "", pub_b64):
            att = "app"
        need = (CFG.get("require") or {}).get(plat, "none")
        # דרישה שאין לה הגדרה בשרת (אין מפתח Turnstile / Play) — לא נאכפת
        if need == "turnstile" and not CFG.get("turnstile_secret"):
            need = "none"
        if need == "integrity" and not (CFG.get("android_package") and CFG.get("play_sa_json")):
            need = "app"
        weak = ATT_RANK.get(att, 0) < ATT_RANK.get(need, 0)
        STATS.setdefault("handshakes", {}).setdefault(plat, {}).setdefault(att, 0)
        STATS["handshakes"][plat][att] += 1
        if weak and CFG.get("mode") == "enforce":
            raise HTTPException(status_code=403, detail="האפליקציה לא אומתה")
        spriv = ec.generate_private_key(ec.SECP256R1())
        shared = spriv.exchange(ec.ECDH(), cpub)
        sid = secrets.token_urlsafe(18)
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=sid.encode(), info=b"zovex-v1").derive(shared)
        spub = spriv.public_key().public_bytes(serialization.Encoding.X962,
                                               serialization.PublicFormat.UncompressedPoint)
        ipm = ip.rsplit(".", 1)[0] + ".x" if "." in ip else ip[:12] + "…"
        with _lock:
            SES[sid] = {"k": key.hex(), "plat": plat, "att": att, "weak": weak, "ip": ipm,
                        "ua": (request.headers.get("user-agent") or "")[:80],
                        "created": now, "exp": now + SESSION_TTL, "last": now}
        _dirty = True
        _persist()
        return {"sid": sid, "spub": _b64u(spub), "exp": int(now + SESSION_TTL), "att": att,
                "server_time": int(time.time() * 1000)}

    @api.post("/admin/tokens")
    async def admin_tokens(req: AdminReq, request: Request):
        global _dirty
        check_panel_password(request, req.password)
        changed = False
        if req.mode in ("off", "monitor", "enforce"):
            CFG["mode"] = req.mode; changed = True
        if isinstance(req.require, dict):
            for p, v in req.require.items():
                if p in PLATS and v in ATT_RANK:
                    CFG["require"][p] = v; changed = True
        if req.rotate in ("android", "pc"):
            CFG["app_secrets"][req.rotate] = secrets.token_urlsafe(32); changed = True
        for f in ("turnstile_sitekey", "turnstile_secret", "android_package"):
            v = getattr(req, f)
            if v is not None:
                CFG[f] = v.strip(); changed = True
        if changed:
            _save(CFG_FILE, CFG)
        if req.sid and req.sid in SES:
            s = SES[req.sid]
            if req.unblock:
                s.pop("blocked", None); s["h"] = {}
            else:
                s["blocked"] = "נחסם ידנית"; s["blocked_at"] = time.time()
            _dirty = True
            _persist(force=True)
        now = time.time()
        active = [(sid, s) for sid, s in SES.items() if s.get("exp", 0) > now]
        active.sort(key=lambda x: (not x[1].get("blocked"), -(x[1].get("n", 0))))
        rows = [{"sid": sid, "plat": s.get("plat"), "att": s.get("att"), "weak": s.get("weak"),
                 "ip": s.get("ip"), "ua": s.get("ua"), "n": s.get("n", 0),
                 "h": {k: v[1] for k, v in (s.get("h") or {}).items() if v[0] == int(now // 3600)},
                 "created": s.get("created"), "last": s.get("last"), "blocked": s.get("blocked")}
                for sid, s in active[:300]]
        by = {}
        for _, s in active:
            k = f'{s.get("plat")}/{s.get("att")}'
            by[k] = by.get(k, 0) + 1
        cfg = {k: v for k, v in CFG.items() if k != "turnstile_secret"}
        cfg["turnstile_secret_set"] = bool(CFG.get("turnstile_secret"))
        cfg["play_ready"] = bool(CFG.get("android_package") and CFG.get("play_sa_json")
                                 and os.path.exists(CFG.get("play_sa_json") or ""))
        return {"cfg": cfg, "stats": STATS, "active": len(active), "by": by,
                "blocked": sum(1 for _, s in active if s.get("blocked")), "rows": rows, "rules": RULES}
