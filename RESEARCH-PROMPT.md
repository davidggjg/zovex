# Deep Research Request: Telegram MTProto Media Streaming at Scale

## Your task

Research how to maximise **download throughput and concurrency** when serving
video to many simultaneous viewers by streaming files out of Telegram over
MTProto. Then give me concrete, implementable answers.

**Search beyond English.** Most of the hard-won knowledge on this lives in
non-English developer communities. Search, read and cite sources in:

- **Russian / Ukrainian** — Habr (habr.com, qna.habr.com), vc.ru, Telegram
  developer chats, GitHub repos with Russian READMEs
- **Persian / Iranian** — Persian dev blogs, forums, Telegram channels
  (Iranian developers build a large share of Telegram file-streaming bots)
- **Indian** — dev.to, Medium, Telegram bot developer groups, the many
  `TG-FileStreamBot` / `FileToLink` forks and their issue trackers
- **Chinese** — V2EX, juejin.cn, GitHub mirrors (Gitee), Telegram groups
- **Turkish, Indonesian, Vietnamese** — same problem space, active communities
- English: GitHub issues, Stack Overflow, Telethon/Pyrogram/gotd/TDLib trackers

For every claim, state **whether it is measured, reported, or marketing**,
and give the source link. Numbers without a source are useless to me.

---

## The system you are advising

- **Backend:** Python 3 + FastAPI + Pyrogram 2.0.106, single server
- **Transport:** raw `functions.upload.GetFile` (NOT `Client.get_file`, NOT
  the HTTP Bot API)
- **Identity:** a pool of **20 active bot tokens** (24 configured), all
  admins in one private content channel
- **Output:** HTTP `206 Partial Content` byte ranges, consumed by our own
  Android app and website players. Nothing is downloaded to disk first.
- **Catalogue:** ~22,500 items, ~3.9 TB, files up to ~4 GB

### Current tuning

| Parameter | Value |
|---|---|
| Media connections per bot, per DC | 4 |
| Request part size | 1 MiB |
| Pipeline depth (requests in flight per stream) | 4 |
| Bot selection | **pinned**: one bot per HTTP request for its whole life |
| Max concurrent viewers routed to one bot | 3 |
| Disk cache | first 6 MB + last 6 MB of each file only |

### The symptom

Smooth all day. After ~21:00 local time, playback starts stalling mid-video
within 10–30 minutes. Measured: **zero FloodWait errors in 24 hours**.

Arithmetic that seems to explain it: one bot with 4 connections delivers
~5 MB/s; 3 viewers share it; 1080p needs ~2 MB/s; at peak each viewer gets
~1.7 MB/s and the player's buffer drains faster than it fills.

**Critical data point:** a Telegram **Premium user account** used to be in the
pool. While it was there, everything was fast. It was removed and performance
collapsed. We cannot rely on Premium (cost, and risk of losing the account).

---

## What we have ALREADY verified — do not repeat this, build past it

1. **TDLib source** (`td/telegram/files/FileDownloadManager.cpp`):
   ```cpp
   void FileDownloadManager::start_up() {
     if (G()->get_option_boolean("is_premium") ||
         G()->get_option_integer("session_count") > 1) {
       max_download_resource_limit_ *= 8;
     }
   }
   ```
   with `int64 max_download_resource_limit_ = 1 << 21;` (2 MiB).
   So `session_count > 1` earns the same 8x in-flight budget as Premium —
   **client-side**.
2. **TDLib `PartsManager.h`**: `MAX_PART_SIZE = 512 << 10` (512 KiB),
   `MAX_PART_COUNT = 4000`, `MAX_PART_COUNT_PREMIUM = 8000`.
3. **TDLib** keeps a **shared resource budget per DC** (`ResourceManager`,
   `Mode::Baseline`), split across concurrent downloads by priority, with a
   separate budget for files under/over 20 KB, and it **cancels in-flight
   parts that fall outside the playback window**.
4. **`FLOOD_PREMIUM_WAIT_X` is real and server-side**: "A wait of X seconds is
   required; the user may also purchase a Telegram Premium subscription to
   remove this limitation."
5. **Measured by `github.com/xwc9527/telebackup`**: 2.16 GB file, **free**
   account, same DC → **7.55 MB/s**, 2214/2214 parts, zero failures; they
   report hitting `FloodPremiumWaitError` for **7–11 seconds per hit** on free
   accounts.
6. **`github.com/scar8969/tgfilestream-py`**: stripes one requested range
   across up to `CONNECTION_LIMIT` = **20 parallel MTProto connections per
   datacenter**, with **128 KiB** parts.
7. Telegram's CDN (`upload.getCdnFile`) needs a public channel with ~100k
   members and is **user-only, not bots** — not available to us.
8. Cloudflare's free/Pro CDN **forbids** serving video from your own origin
   (Enterprise only) — ruled out.
9. **50 admins per channel** is a hard cap, and bots count toward it.
10. Takeout API (`invokeWithTakeout`) relaxes limits but is user-only,
    intended for exporting your own data, has a forced start delay, and using
    it to dodge limits violates the terms — ruled out.

---

## Questions I need answered, in priority order

### A. Parallelism ceiling — the core question

1. What is the **real** ceiling on concurrent MTProto media connections?
   Per **auth key**? Per **bot token**? Per **DC**? Per **source IP**? Give
   evidence. I have seen an unverified claim of a "silent limit of 13
   connections" on Habr — confirm or kill it.
2. Does `upload.getFile` throughput scale linearly with connection count, and
   **where does it stop**? Anyone who measured 4 vs 8 vs 16 vs 20 vs 32?
3. **Optimal part size** for streaming: 128 KiB vs 512 KiB vs 1 MiB. What are
   the real trade-offs for *latency to first byte* versus *sustained
   throughput*? Why does TDLib cap at 512 KiB while others use 128 KiB?
4. Is the `precise` flag on `upload.getFile` relevant to streaming, and what
   does it actually change?

### B. Bots versus user accounts

5. Is there a **documented or measured** throughput difference between a bot
   token and a user account over MTProto (not the Bot API)? If yes, what is
   the mechanism and how large is the gap?
6. Does `FLOOD_PREMIUM_WAIT` fire for **bot** accounts, or only for
   non-Premium **users**? Evidence either way.
7. Are `upload.getFile` limits enforced per token, per IP, or both? If
   per-token, how many tokens have people run in parallel from a single IP
   before something broke?
8. Does **Premium on one account** raise only that account's limits, or does
   anything propagate (e.g. to a channel's files)?

### C. Scaling the pool

9. Beyond the 50-admin cap, are there practical limits to running many bot
   tokens against one channel from one server? What breaks first?
10. **Is it better** to have many bots with few connections each, or few bots
    with many connections each? Anyone who tested both?
11. What do production file-streaming services actually run? Real
    configurations from projects serving thousands of concurrent viewers.

### D. Architecture and caching

12. Best practice for striping ONE viewer's byte range across multiple
    connections while still delivering bytes **in order, immediately**, with
    no buffering burst. Concrete implementations welcome.
13. How do mature projects implement **read-ahead / prefetch** for video
    playback without wasting bandwidth on seeks?
14. Caching: does anyone cache Telegram file ranges on local disk by
    popularity? What hit rates and what eviction policy? Is `nginx`
    `slice` + `proxy_cache` in front of a byte-range origin a known-good
    pattern for this, and what are its failure modes?
15. `file_reference` expiry during long streams: how do production systems
    refresh it without interrupting playback?

### E. Error handling under high concurrency

16. Correct handling of `FLOOD_PREMIUM_WAIT`: back off **one connection**, or
    the whole account? How long, and how should the client ramp back up?
17. Is there a known-good **adaptive concurrency controller** (TCP-style
    additive-increase / multiplicative-decrease) for Telegram downloads?
    Anyone who shipped one?
18. `AUTH_KEY_DUPLICATED` — what exactly triggers a ban, and what are the safe
    boundaries for running multiple sessions on one account?

### F. Anything we have not thought of

19. Obscure, non-obvious techniques from any community that materially change
    throughput or latency for this workload. Undocumented flags, DC selection
    strategies, connection reuse patterns, transport tricks (e.g.
    `TCPAbridged` vs `TCPIntermediate` vs obfuscated transports), anything.
20. What do people **regret** building? Which optimisations turned out to
    cause bans, instability, or no measurable gain?

---

## Rules for your answer

- **Cite every source.** Link it. Say which language/community it came from.
- **Label each claim** `MEASURED` (with method), `REPORTED` (anecdote), or
  `MARKETING`.
- **Give numbers**, not adjectives. "Faster" is worthless; "7.55 MB/s on a
  2.16 GB file, free account, same DC" is useful.
- **Flag anything that risks an account ban or violates Telegram's terms**, and
  say so explicitly rather than recommending it.
- Where you disagree with something in my "already verified" list, say so and
  show why.
- Prefer **primary sources**: source code, official docs, issue trackers,
  benchmark output. Vendor blogs are the weakest evidence.
- End with a **ranked, concrete action list** for my exact configuration
  above: which parameter to change, to what value, and what evidence supports
  it.
