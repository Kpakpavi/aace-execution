# AACE — 1-Week MVP Plan

**Owner:** Ahlonko
**Restarted:** 2026-05-25 (Mon) after one-week pause
**Target launch:** 2026-05-31 (Sun)
**Pace:** 2–3 hrs/day (~15 hrs total)
**Scope:** Smallest thing that can detect one real arbitrage deal across ≥2 sources and webhook it to the AI agent. Everything else deferred.

**Definition of done:**
1. 2 connectors live and feeding the pipeline (Slickdeals + Reddit).
2. Cross-source matcher buckets listings by product_key.
3. Webhook handoff to the AI agent working end-to-end with HMAC signing, retries, and dedup.
4. APScheduler runs the full loop every 15–30 min unattended.
5. VPS deployment running 24/7.
6. **One real arbitrage deal acted on**, sourced through AACE → agent → you → buy.
7. `v0.1.0` tagged on GitHub.

Out of scope (post-v0.1.0): DealNews, Woot, eBay, Keepa, Best Buy, Walmart/Target/Newegg/Costco scrapers, AliExpress, Temu, StockX, Mercari, FB Marketplace, Sentry polish, GitHub Actions CI, dashboard observability panel.

---

## What's already done (banked before today)

- ✅ FastAPI app with 11 endpoints + X-API-Key auth middleware
- ✅ 6-stage pipeline + workers + persistence + ~10 tests
- ✅ Dockerfile + docker-compose.yml (postgres + api + dashboard, networked)
- ✅ Streamlit dashboard wired via env vars
- ✅ Public GitHub repo at github.com/Kpakpavi/aace-execution
- ✅ MIT LICENSE + real README committed
- ⚠️ Connector framework (`base.py`) + Slickdeals connector + 19 tests — **written but uncommitted and unverified**. Day 1 closes this.

---

## Decisions locked

| Question | Answer |
|---|---|
| Handoff to AI agent | Webhook (POST to `AGENT_WEBHOOK_URL`, HMAC-signed) |
| Email / SMS code | DROPPED — agent's job |
| Sentry / CI | Deferred to post-v0.1.0 |
| VPS | YES — deploy for 24/7 ops |
| Connector breadth | 2 only (Slickdeals + Reddit). More post-v0.1.0. |
| Auth-requiring sources (eBay, Keepa, Best Buy) | Deferred — signup friction kills the 1-week budget. |

---

## Working principles

1. **Framework first, connectors as plug-ins.** Slickdeals + Reddit prove the framework. Adding the next 10 sources should be ~50 lines each post-v0.1.0.
2. **Webhook is the only output channel from AACE.** No email, no SMS.
3. **Every connector ships with a fixture-based test** before merging.
4. **Earning is the gate.** v0.1.0 only tags when one real deal flowed Source → AACE → Agent → You → Buy.

---

## Day 1 — Mon May 25 — Verify + commit Slickdeals (~2h)

The framework + Slickdeals + 19 tests are already on disk. Today closes them out.

1. `cd ~/Claude_Projects/aace-execution && uv sync` (pulls feedparser, httpx).
2. `uv run pytest tests/test_slickdeals_connector.py -v` — all 19 tests must pass.
3. Smoke test against real feed: `uv run python -c "from aace_execution.connectors.slickdeals import SlickdealsConnector; c = SlickdealsConnector(); [print(item.title, '→', item.price) for item in c.run()[:5]]"`
4. Commit + push: `connectors/`, `tests/test_slickdeals_connector.py`, `pyproject.toml`, `PLAN.md`.

**Evidence:** Green test run + 5 real Slickdeals titles printed + commit on `main`.

## Day 2 — Tue May 26 — Reddit connector (credential-free) (~2-3h)

`src/aace_execution/connectors/reddit.py`:
- Fetches `https://www.reddit.com/r/deals+buildapcsales+GameDeals+Frugal/new.json` — no OAuth, no signup, just polite User-Agent + low call rate.
- Reuses the price-extraction regex from Slickdeals (factor into `connectors/base.py` as `_extract_price`).
- Skips posts without parseable price.
- Tests with embedded JSON fixture (no network).

**Evidence:** `uv run pytest tests/test_reddit_connector.py -v` green. Smoke run prints 5+ real Reddit deal titles + prices.

## Day 3 — Wed May 27 — Cross-source matcher (~2-3h)

Pipeline currently expects pre-matched listings for one product. We need the layer in front.

`src/aace_execution/pipeline/cross_source_matcher.py`:
- Input: flat `list[NormalizedListing]` from all connectors in a run.
- Bucket by `product_key` (already produced by each connector).
- For each bucket with ≥2 distinct sources, emit one `RunPipelineRequest` (matching `api/models.py`).
- Buckets with only one source are dropped (no discrepancy to detect yet).

Tests cover: empty input, single-source bucket dropped, two-source bucket emitted, three-source bucket emitted, ties broken deterministically.

**Evidence:** Unit tests green. Manual run with mixed Slickdeals+Reddit fixture produces ≥1 pipeline request.

## Day 4 — Thu May 28 — Webhook outbound to AI agent (~2-3h)

`src/aace_execution/integrations/agent_webhook.py`:
- Reads `AGENT_WEBHOOK_URL` + `AGENT_WEBHOOK_SECRET` from env.
- On opportunities with `score >= WEBHOOK_SCORE_THRESHOLD`, POSTs JSON with `X-AACE-Signature: sha256=<hmac>` header.
- Exponential backoff: 1s → 5s → 30s → 5min → give up + log.
- `webhook_deliveries` table (new SQL migration): `opportunity_id`, `status`, `attempts`, `last_response_code`, `last_error`, `sent_at`.
- Dedup: never send the same `opportunity_id` twice within 24h.
- Wires into the existing `alert_decision_worker` as the "send" action.

**Evidence:** Mocked httpx test: signed POST goes out, retry on 503, dedup blocks 2nd send. Real test: webhook.site URL receives one signed POST.

## Day 5 — Fri May 29 — Scheduler + worker process (~2-3h)

`src/aace_execution/worker.py` (new entry point: `python -m aace_execution.worker`):
- APScheduler in-process, BlockingScheduler.
- Every 30 min: run all registered connectors → cross-source matcher → for each bucket POST to `/run-pipeline` internally → if scored opportunity, fire webhook.
- Staggered start to avoid herd.
- Add a `worker` service to `docker-compose.yml` alongside `api` + `dashboard` + `postgres`.

**Evidence:** `docker compose up -d`, wait 30 min, return — `pipeline_results` rows show recent runs across both sources.

## Day 6 — Sat May 30 — VPS deploy (~2-3h)

- Provision Hetzner CX22 (~€4/mo) or DO basic ($6/mo). Ubuntu 24.04, 4GB RAM.
- Harden: non-root user, SSH keys only, UFW (22 + 443), fail2ban.
- Install Docker + Compose plugin.
- Clone repo, fill `.env` with prod values (real `AACE_API_KEY`, `AGENT_WEBHOOK_URL`, `AGENT_WEBHOOK_SECRET`, strong `POSTGRES_PASSWORD`).
- `docker compose up -d --build`.
- Systemd `aace.service` so it survives reboot.
- Tailscale-only access for dashboard + Postgres. No public ports beyond the webhook target (and that's outbound only — nothing inbound needed except SSH).

**Evidence:** SSH disconnect + `reboot` → stack auto-starts. Dashboard reachable via Tailscale. Worker logs show fresh fetches.

## Day 7 — Sun May 31 — Live shakedown + first real deal + v0.1.0 (~2-3h)

- Stack has been running ~12-24h by now. Audit:
  - `pipeline_results` — how many runs, how many opportunities, how many cross-source matches.
  - `webhook_deliveries` — delivery rate, retry rate.
  - Source-by-source noise level.
- Tune `WEBHOOK_SCORE_THRESHOLD` so the agent only gets real signal.
- **Act on one real deal** — the gate, not the tag.
- Tag `v0.1.0` on GitHub.
- Update README with one-paragraph status (what's live, what's deferred).

**Evidence:** v0.1.0 release on GitHub. Live VPS. **One real purchase made from an AACE-surfaced deal.**

---

## Cut order if a day slips

Lose these in order before losing the launch:

1. Tailscale (Day 6) — accept public-IP dashboard temporarily, basic-auth it.
2. Systemd unit (Day 6) — just leave `docker compose` running, restart manually if needed.
3. Live shakedown audit polish (Day 7) — eyeball logs, skip the formal audit.
4. The Reddit connector itself, AS A LAST RESORT (Day 2) — Slickdeals alone can't trigger the matcher (single source). If pulled, the matcher work still ships dormant; first deal slips to week 2.

Do NOT cut: Slickdeals verification, cross-source matcher, webhook, scheduler, VPS deploy, first real deal.

---

## Risk register

| Risk | Mitigation |
|---|---|
| Slickdeals + Reddit don't overlap enough → matcher emits 0 buckets | Both feeds cover consumer electronics / Costco / Frugal — overlap is real. If not, broaden Reddit subs in `REDDIT_SUBS` env. |
| Reddit rate-limits the public JSON endpoint | Polite User-Agent + max 1 req/sub/min. Cache responses. If still blocked, add 30s sleep between subs. |
| Webhook delivery silently failing | `webhook_deliveries` table is the audit trail. Manually check on Day 7. Add Sentry post-v0.1.0. |
| VPS breach | UFW + fail2ban + SSH-keys-only. Tailscale-only ingress for dashboard. |
| 7-day pace too aggressive given 2-3 hrs/day | Cut order above. Worst case: ship v0.1.0 Day 8 or 9, not Day 7. |

---

## Daily ritual

1. Pull `main`, branch `day-NN-<short>`.
2. One step at a time. Each session: state task, write code, run tests, commit.
3. EOD: PR → merge → push.
4. Update `JOURNAL.md` — shipped / blocked / next.

---

## Post-v0.1.0 roadmap (week 2+, opportunistic)

Once one real deal is in the books, expand connector breadth in priority order:

1. DealNews + Woot RSS (~1 day, framework already done).
2. eBay (if signup approved) — high-value because of sold comps.
3. Generic YAML-driven scraper + Walmart + Target configs.
4. Amazon via Keepa (when ready to spend $20/mo).
5. Newegg + Costco scrapers.
6. Sentry + GitHub Actions CI + structured logs + `/metrics`.
7. International / resale (AliExpress, Temu, StockX, Mercari, FB Marketplace).
