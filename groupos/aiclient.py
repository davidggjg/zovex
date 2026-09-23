#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aiclient — השליחה בפועל. הרשת, ורק היא.

## מה כאן ומה לא

ההחלטה מה לשאול ואיך לפרש נמצאת ב-‎ai‎; הבחירה איזה מפתח ב-‎aikeys‎;
מה לעשות עם התוצאה ב-‎policy‎. כאן נשארה רק הבקשה עצמה — ולכן אפשר
להחליף ספק בלי לגעת בשום מודול אחר.

## שני ספקים, שתי צורות

Groq מדבר בפורמט של OpenAI; Gemini בפורמט משלו. ההבדל נגמר בשתי
פונקציות בניית גוף ובשתי פונקציות חילוץ טקסט — כל השאר משותף.

## פסק זמן

שש שניות. הודעה בקבוצה נבדקת **תוך כדי** שהיא מוצגת לכולם, ואיחור
של עשרים שניות פירושו שהספאם כבר נקרא. עדיף לוותר על הבדיקה מאשר
לעכב אותה.

## כישלון פתוח, תמיד

רשת נופלת, מכסות נגמרות, ספקים משנים סכימות. בכל אחד מהמקרים
התוצאה היא "אין אות" ולא "חשוד". הקבוצה ממשיכה לעבוד גם כשה-AI לא.

## מה נשלח החוצה

**טקסט ההודעה בלבד** — בלי שם, בלי מזהה, בלי היסטוריה. מי ששולח
תוכן של אנשים לספק חיצוני צריך לשלוח את המינימום, וזה המינימום.
הפיצ'ר כבוי כברירת מחדל, ומנהל מדליק אותו ביודעין.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import ai
import aikeys

log = logging.getLogger("groupos.ai")

TIMEOUT = 6.0
MAX_TOKENS = 120        # התשובה היא JSON קצר; יותר מזה הוא בזבוז

ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/models/"
               "{model}:generateContent"),
}

MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "gemini": "gemini-2.0-flash",
}


# ── בניית הבקשה ───────────────────────────────────────────────────────────
def build_request(provider: str, key: str, system: str,
                  prompt: str) -> tuple[str, dict, dict]:
    """‎(url, headers, body)‎. טהור — נבדק בלי רשת."""
    if provider == "groq":
        return (
            ENDPOINTS["groq"],
            {"Authorization": f"Bearer {key}",
             "Content-Type": "application/json"},
            {"model": MODELS["groq"],
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": prompt}],
             "temperature": 0,
             "max_tokens": MAX_TOKENS,
             "response_format": {"type": "json_object"}},
        )
    if provider == "gemini":
        return (
            ENDPOINTS["gemini"].format(model=MODELS["gemini"]),
            # המפתח בכותרת ולא ב-URL: URL נכנס ליומני שרת ולפרוקסי
            {"x-goog-api-key": key, "Content-Type": "application/json"},
            {"systemInstruction": {"parts": [{"text": system}]},
             "contents": [{"role": "user", "parts": [{"text": prompt}]}],
             "generationConfig": {"temperature": 0,
                                  "maxOutputTokens": MAX_TOKENS,
                                  "responseMimeType": "application/json"}},
        )
    raise ValueError(f"ספק לא מוכר: {provider}")


def extract_text(provider: str, data: Any) -> str:
    """הטקסט מתוך תשובת הספק. סכימה שהשתנתה מחזירה ריק ולא מפילה."""
    try:
        if provider == "groq":
            return data["choices"][0]["message"]["content"]
        if provider == "gemini":
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return ""
    return ""


def retry_after_of(headers: Any) -> Optional[float]:
    try:
        v = headers.get("Retry-After") or headers.get("retry-after")
        return float(v) if v else None
    except (TypeError, ValueError, AttributeError):
        return None


# ── הלקוח ─────────────────────────────────────────────────────────────────
class AIClient:
    """שולח, מדווח לבריכה, ומחזיר ‎Verdict‎. לעולם לא זורק."""

    def __init__(self, providers: aikeys.Providers,
                 cache: Optional[ai.Cache] = None,
                 transport=None, timeout: float = TIMEOUT):
        self.providers = providers
        self.cache = cache or ai.Cache()
        # ‎transport(url, headers, body, timeout)‎ → ‎(status, headers, json)‎.
        # הזרקה ולא יבוא קשיח, כדי שהבדיקות ירוצו בלי רשת ובלי מפתח.
        self.transport = transport or _aiohttp_transport
        self.timeout = timeout
        self.calls = 0
        self.failures = 0

    async def analyze(self, text: str, *, lang: str = "",
                      context: str = "") -> ai.Verdict:
        fp = ai.fingerprint(text)
        hit = self.cache.get(fp)
        if hit is not None:
            return hit

        prompt = ai.build_prompt(text, lang=lang, context=context)
        # ניסיון לכל ספק זמין. מכסה שנגמרה אצל אחד אינה סוף הבדיקה.
        for _ in range(len(self.providers.pools) or 1):
            picked = self.providers.pick()
            if picked is None:
                return ai.FAILED
            provider, key = picked
            v = await self._one(provider, key, prompt)
            if not v.failed:
                self.cache.put(fp, v)
                return v
        return ai.FAILED

    async def _one(self, provider: str, key: str, prompt: str) -> ai.Verdict:
        try:
            url, headers, body = build_request(provider, key, ai.SYSTEM, prompt)
        except ValueError:
            return ai.FAILED
        self.calls += 1
        try:
            status, resp_headers, data = await asyncio.wait_for(
                self.transport(url, headers, body, self.timeout),
                timeout=self.timeout + 1)
        except asyncio.TimeoutError:
            self.failures += 1
            self.providers.fail(provider, key, status=None)
            log.warning("AI %s: פסק זמן", provider)
            return ai.FAILED
        except Exception as e:                       # noqa: BLE001
            # רשת נופלת בדרכים רבות ומשונות. אף אחת מהן אינה סיבה
            # להפיל טיפול בהודעה בקבוצה.
            self.failures += 1
            self.providers.fail(provider, key, status=None)
            log.warning("AI %s נכשל: %s", provider, e)
            return ai.FAILED

        if status != 200:
            self.failures += 1
            wait = self.providers.fail(provider, key, status=status,
                                       retry_after=retry_after_of(resp_headers))
            log.warning("AI %s החזיר %s · מפתח %s מצונן %.0fש",
                        provider, status, aikeys.mask(key), wait)
            return ai.FAILED

        self.providers.ok(provider, key)
        v = ai.parse_verdict(extract_text(provider, data), provider)
        if v.failed:
            self.failures += 1
            log.warning("AI %s: תשובה שלא נפרסה", provider)
        return v

    def stats(self) -> dict:
        return {"calls": self.calls, "failures": self.failures,
                "cache": self.cache.stats()}


async def _aiohttp_transport(url: str, headers: dict, body: dict,
                             timeout: float):
    """המימוש האמיתי. מיובא בפנים כדי שהמודול ייטען גם בלי aiohttp."""
    import aiohttp
    async with aiohttp.ClientSession() as s:
        async with s.post(url, headers=headers, json=body,
                          timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            try:
                data = await r.json(content_type=None)
            except (ValueError, json.JSONDecodeError):
                data = {}
            return r.status, r.headers, data
