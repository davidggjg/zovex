#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מודד כל שלב ביחידה אחת בנפרד, כדי לראות מי אוכל את 56 השניות."""
import importlib.util, json, time, urllib.parse, urllib.request, sys

spec = importlib.util.spec_from_file_location("m", "/opt/zovex-bot/tmdb_ai_match.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

tkey = m.load_key("TMDB_API_KEY")
lkey = m.load_key("LLM_API_KEY", "GROQ_API_KEY")
print(f"מפתחות: TMDB {'✓' if tkey else '✗'} · LLM {'✓' if lkey else '✗'}\n")

name = sys.argv[1] if len(sys.argv) > 1 else "השמיניה"
t = time.time(); q, yr = m.clean(name)
print(f"1. clean()            {time.time()-t:6.2f}s  → {q!r} שנה={yr!r}")

qs = [q] + ([f"{q} {yr}"] if yr else [])
print(f"\n2. חיפושי TMDB ({len(qs)*2} קריאות):")
for nm in qs:
    for lang in ("he-IL", "en-US"):
        u = f"{m.TMDB}/search/multi?" + urllib.parse.urlencode(
            {"api_key": tkey, "query": nm, "language": lang, "include_adult": "false"})
        t = time.time()
        try:
            r = m.http_json(u, timeout=m.TMDB_TIMEOUT, retries=1)
            n = len(r.get("results") or [])
            print(f"   {lang} {nm[:22]:<24} {time.time()-t:6.2f}s  {n} תוצאות")
        except Exception as e:
            print(f"   {lang} {nm[:22]:<24} {time.time()-t:6.2f}s  ✗ {type(e).__name__}: {str(e)[:50]}")

t = time.time(); cands = m.tmdb_candidates(tkey, qs)
print(f"   סה\"כ tmdb_candidates {time.time()-t:6.2f}s  → {len(cands)} מועמדים")
print(f"   כשלים שנספרו: {dict(m.TMDB_FAILS) or 'אין'}")

cfg = {"provider":"groq","base_url":"https://api.groq.com/openai/v1",
       "model":"qwen/qwen3.8-27b","key":lkey}
t = time.time()
try:
    ans = m.ask_model(cfg, name, cands, yr)
    print(f"\n3. ask_model()        {time.time()-t:6.2f}s  → {ans}")
except Exception as e:
    print(f"\n3. ask_model()        {time.time()-t:6.2f}s  ✗ {type(e).__name__}: {str(e)[:90]}")
