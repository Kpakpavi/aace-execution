# AACE — 2-Week Execution Plan (Full Scope)

**Owner:** Ahlonko
**Started:** 2026-05-17 (Sun)
**Target launch:** 2026-05-30 (Sat)
**Pace:** 5+ hrs/day, no buffer days
**Definition of done:** Live VPS deployment, 5 data sources active (Slickdeals, Reddit, eBay, Amazon/Keepa, generic web), real email + SMS alerts firing on scored opportunities, clean public GitHub repo, first real arbitrage deal acted on.

---

## Reality check (inspected 2026-05-17)

**Built and working** in `/Users/kwadjossanisaackpakpavi/Claude_Projects/aace-execution`:
- FastAPI app `src/aace_execution/api/main.py` with 11 endpoints
- `X-API-Key` auth middleware (reads `AACE_API_KEY` env)
- Pipeline runner + 4 workers (input validator, discrepancy, scoring, alert decision)
- Postgres persistence layer + `sql/schema.sql`
- 10 test files
- `pyproject.toml` (Python 3.11, uv-managed)

**Not built yet (despite earlier summary):**
- ❌ No `Dockerfile`, no `docker-compose.yml`
- ❌ No dashboard code
- ❌ No connectors to any real source
- ❌ No email/SMS alerting
- ❌ No scheduler, no CI
- ❌ Empty `README.md`

**Git state:** Old `.git.backup` with 3 commits + remote at `github.com/Kpakpavi/aace-execution`. Decision: archive old as `aace-execution-legacy`, init fresh.

---

## Decisions locked

| Question | Answer |
|---|---|
| Sources | Amazon (Keepa), eBay, Slickdeals RSS, Reddit, generic web |
| Alerts | Email (SendGrid) + SMS (Twilio, hot deals only) |
| Deploy | Local-only / your own VPS |
| Repo visibility | Public (sanitized) |
| Git strategy | Fresh start, archive old repo |
| Timeline | 2 weeks at 5+ hrs/day |

---

## Critical Day-1 admin (do these FIRST thing Sunday morning, in parallel with code work)

These have signup/approval lead times — start them before any coding so they're ready when you need them.

1. **eBay Developer account** — register at developer.ebay.com, request Browse + Marketplace Insights access. Approval can take a day.
2. **Keepa API** — sign up, choose a plan (~$20/mo cheapest), grab API key.
3. **SendGrid** — free tier signup, complete sender verification (the email-domain auth step takes a few hours of DNS propagation).
4. **Twilio** — sign up, buy a phone number (~$1/mo).
5. **VPS provider** — pick Hetzner (CX22 ~€4/mo) or DigitalOcean ($6/mo). Don't provision yet — just have the account ready.
6. **Domain or subdomain** — pick the hostname you'll use (`aace.<yourdomain>`). Or skip and use Tailscale.
7. **Sentry** — free-tier account.

---

## Working principles

1. **One step at a time, evidence-gated.** Every change verified before the next.
2. **Claude.md drives Claude Code sessions.** Read it and summarize rules before each prompt.
3. **No secrets in git, ever.** Sanitize BEFORE first commit. `.env` gitignored. `.env.example` is the contract.
4. **Real data over synthetic.** Once a connector lands, the next run uses live data.
5. **Earning is the gate.** Plan is "done" when a real deal has been surfaced, alerted, and acted on.

---

# WEEK 1 — Foundation + Docker + Dashboard + Connectors (Days 1–7)

## Day 1 — Sun May 17 — Sanitize + fresh git + new public repo
**Parallel admin:** Start all signups in the "Critical Day-1 admin" section above.

Code tasks:
- Audit for hardcoded secrets (`grep -rn` for keys/passwords across `src/`, `scripts/`, `examples/`).
- Write proper `.gitignore` (Python + uv + `.venv` + `.env` + `.DS_Store` + `.pytest_cache` + `.ruff_cache` + `.git.backup`).
- Write `.env.example` covering every env var the code reads.
- Write a real `README.md` — tagline, mermaid architecture diagram, endpoints table, local-dev steps.
- Add `LICENSE` (MIT).
- On GitHub web: rename `Kpakpavi/aace-execution` → `Kpakpavi/aace-execution-legacy`.
- Delete `.git.backup` locally.
- `git init`, first clean commit, create new public `Kpakpavi/aace-execution`, push `main`, protect `main`.

**Evidence:** New GitHub URL renders, README looks good, no secrets in any tracked file.

## Day 2 — Mon May 18 — Dockerfile + docker-compose (API + Postgres)

- Write `Dockerfile` for API (python:3.11-slim, `uv sync --frozen`, uvicorn).
- Write `docker-compose.yml`: `db` (postgres:16 with `sql/schema.sql` mounted to `/docker-entrypoint-initdb.d/`, named volume), `api` (depends_on db with healthcheck).
- All env from `.env`, with healthcheck on the API service.
- `docker compose down -v && docker compose up --build` — verify schema auto-init and full pipeline call works.

**Evidence:** `curl -H "X-API-Key: ..." http://localhost:8000/run-pipeline` returns 200; `/opportunities` shows the row.

## Day 3 — Tue May 19 — Verify analytics endpoints + Streamlit dashboard MVP

- Audit the 11 endpoints in `api/main.py` against the 5 analytics (`opportunity-summary`, `top-products`, `alert-rate`, `high-score-opportunities`, `daily-opportunities`). Implement any gaps with tests.
- Create `dashboard/app.py`. Read `AACE_API_BASE_URL` (default `http://localhost:8000`) + `AACE_API_KEY` from env. Send `X-API-Key`.
- Pages: Summary, Hot deals, Daily trend, Top products, Filterable opportunities table.
- Verify locally with `streamlit run dashboard/app.py`.

**Evidence:** All 5 analytics tested green. Dashboard renders all 4 panels from local API.

## Day 4 — Wed May 20 — Dockerize dashboard + tag v0.1.0

- Write `dashboard/Dockerfile`.
- Add `dashboard` service to compose (`AACE_API_BASE_URL=http://api:8000`).
- `docker compose down -v && docker compose up --build` — full stack.
- Add a couple of screenshots to README. Tag `v0.1.0` ("Foundation").

**Evidence:** `http://localhost:8501` works; dashboard hits `api` via internal Docker network.

## Day 5 — Thu May 21 — Connector framework + Slickdeals + Reddit

- Create `src/aace_execution/connectors/` package.
- Define `Connector` protocol: `fetch() -> list[RawItem]`, `normalize(raw) -> Opportunity`.
- Build `connectors/slickdeals.py` (RSS parser). Wire as pipeline input source.
- Build `connectors/reddit.py` (PRAW or read-only JSON). Subs configurable via env (`REDDIT_SUBS`).
- Dedup by URL/ASIN across both.
- Tests with stored fixtures.

**Evidence:** Pipeline run pulls real Slickdeals + Reddit opportunities into Postgres, both source tags visible.

## Day 6 — Fri May 22 — eBay + Amazon/Keepa connectors

(eBay dev approval should be in by now — if not, swap Day 6 ↔ Day 7.)

- Build `connectors/ebay.py`: Browse API for active listings, Marketplace Insights for sold comps (the "true market price" for arbitrage scoring).
- Build `connectors/keepa.py`: pull product price history + current Amazon price by ASIN. Cache responses in Postgres (Keepa tokens are limited).
- Both seeded by ASIN/keyword lists from env.

**Evidence:** Given seed ASINs, pipeline produces scored opportunities with Amazon price vs. retailer/eBay price.

## Day 7 — Sat May 23 — Generic web scraper + tag v0.2.0

- Build `connectors/web.py` with `httpx` + `selectolax`. Respect `robots.txt`, rate-limit per host, identifying user-agent.
- YAML config per target retailer (CSS selectors). Start with 2–3 retailers that match your arbitrage angle (e.g., Best Buy, Target, Walmart).
- Tag `v0.2.0` ("Data sources live").

**Evidence:** Scraping a configured retailer page yields normalized opportunities. All 5 sources active.

---

# WEEK 2 — Alerts + Scheduler + CI + Deploy + Earn (Days 8–14)

## Day 8 — Sun May 24 — Email alerts (SendGrid)

- Build `src/aace_execution/alerts/email.py`. HTML template with deal summary, score, link, source. Modes: per-alert (score ≥ threshold) + daily digest.
- Wire into `alert_decision_worker` so high-score deals route here.
- Tests with `unittest.mock`.

**Evidence:** Trigger pipeline with seeded high-score deal → email arrives.

## Day 9 — Mon May 25 — SMS alerts (Twilio)

- Build `alerts/sms.py`. Strict gates: fires only when `score >= HOT_SCORE_THRESHOLD` AND `SMS_DAILY_BUDGET` (default $1.00) not exceeded.
- Persist sent-SMS log to Postgres → no duplicates.
- Daily cap exceeded → fallback to email.

**Evidence:** Seed a very-high-score deal → SMS arrives. Re-run → no duplicate. Force cap hit → email fallback fires.

## Day 10 — Tue May 26 — Scheduler + observability

This is a heavy day — split it as 2.5 hrs scheduler / 2.5 hrs observability.

Scheduler:
- Add APScheduler (in-process inside API container or separate `scheduler` service in compose).
- Default cadence: every 30 min per connector, configurable.
- Stagger to avoid simultaneous hits.
- Persist `pipeline_runs` table (run_id, started_at, source, n_opportunities, duration_ms, status).

Observability:
- Structured JSON logs (`python-json-logger`).
- Sentry SDK in API + dashboard.
- `/metrics` endpoint (Prometheus-format: opportunities by source, alerts sent, last run timestamp).
- Dashboard "Pipeline health" panel: last run per source, error count last 24h.

**Evidence:** `docker compose up` and walk away — `pipeline_runs` grows every 30 min. Force a connector error → Sentry issue + dashboard red.

## Day 11 — Wed May 27 — GitHub Actions CI + repo polish

- `.github/workflows/ci.yml`: on push, `uv sync` + `pytest` + `ruff check` + `docker build` for both images.
- Branch protection requires green CI before merge.
- Add CI badge to README.
- Polish README: screenshots from real dashboard, full env-var table, "How it works" section, contribution notes (or "personal project — no PRs" if you prefer).

**Evidence:** Deliberate broken commit → CI red. Fix → green. Badge updates.

## Day 12 — Thu May 28 — VPS provisioning + first deploy

- Spin up Hetzner CX22 / DO droplet (Ubuntu 24.04, 2GB RAM min).
- Harden: non-root user, SSH keys only, UFW (22 + 80 + 443), fail2ban.
- Install Docker + Compose plugin.
- Clone repo, drop `.env` (filled), `docker compose up -d --build`.
- Systemd unit `aace.service` so the stack restarts on reboot.

**Evidence:** Reboot VPS → stack comes back up automatically. API reachable on port 8000 from your machine.

## Day 13 — Fri May 29 — HTTPS + auth (Caddy or Tailscale)

Pick one — Tailscale is simpler and safer for a personal earning tool.

Option A — Caddy (public dashboard):
- Install Caddy on host.
- Caddyfile with `aace.<yourdomain>` → reverse-proxy to localhost:8501.
- TLS auto-handled. Basic auth on dashboard route.

Option B — Tailscale (private dashboard, recommended):
- Install Tailscale on VPS and on your laptop/phone.
- Dashboard reachable only via Tailscale IP. No public exposure.

**Evidence:** Dashboard reachable via your chosen method, properly secured. Cert valid (Caddy) or Tailscale-only (Option B).

## Day 14 — Sat May 30 — Monetization shakedown + v1.0.0

- Let the system run a full real day before this point — review every alert that fired in the last 48h.
- Tune scoring thresholds and alert thresholds against actual signal-to-noise.
- Write `docs/PLAYBOOK.md`: which source × category combos are profitable, what discount % is "real," shipping/return policies that matter.
- Track every alert in a `alert_outcomes` table (or spreadsheet): real / noise, actionable, executed, P&L.
- Take fresh dashboard screenshots, update README, write `CHANGELOG.md`.
- Tag `v1.0.0` ("Live earning system").
- **Act on at least one alert** — this is the gate, not the tag.

**Evidence:** v1.0.0 on GitHub. Live URL/Tailscale. First real deal logged in `alert_outcomes`.

---

## Daily ritual

1. Pull `main`, branch `day-NN-<short>`.
2. Open `Claude.md` — confirm rules before any code-gen prompt.
3. One step at a time. Each Claude Code prompt: state task, constraint ("modify only X"), required output ("show diff only"). Evidence between steps.
4. EOD: PR → merge → push → `docker compose up --build` sanity check.
5. Update `JOURNAL.md` — shipped / blocked / next.

---

## Risk register

| Risk | Mitigation |
|---|---|
| eBay API approval slow | Apply Day-1 morning. If not approved by Day 6, swap with Day 7 work. |
| Keepa cost spike | Aggressive caching; hard daily-token budget. |
| Twilio runaway loop | Hard `SMS_DAILY_BUDGET`; per-deal dedup table. |
| Connector returns garbage | Fixture-based tests; prod logs sample raw payloads (no secrets). |
| Scraper gets IP banned | Honor robots.txt, rate-limit, rotate UA, back off on 429. |
| Secret leak in git history | Sanitize BEFORE first commit Day 1. Use `git-secrets` pre-commit hook. |
| VPS breach | UFW + fail2ban + SSH-keys-only + Tailscale. |
| 2-week pace too aggressive | Days 6, 7, 10 are the risk concentrations. If a day slips, cut: web scraper (Day 7) is the most droppable; observability dashboards (Day 10) can be done after launch. CI (Day 11) can also slip post-launch. |

---

## Compression notes vs. the earlier 3-week version

To fit full scope into 14 days, four things were collapsed:

- **Day 3 doubled up** — analytics-endpoint audit + dashboard MVP same day (both small if endpoints already exist).
- **Day 5 doubled up** — Slickdeals + Reddit same day (both genuinely simple, free, similar shape).
- **Day 10 is the heaviest day** — scheduler AND observability. The fallback is: ship scheduler, defer Sentry/metrics to a v1.1 if needed.
- **Buffer day removed** — Day 7 in the old plan was buffer; now it's the web scraper.

If you hit the wall on any day, the cut order is:
1. Generic web scraper (Day 7)
2. Sentry/metrics half of Day 10
3. CI (Day 11)
4. Caddy/HTTPS (Day 13) — use Tailscale instead, zero work.

Don't cut: connectors, alerts, scheduler, VPS deploy, monetization shakedown.

---

## Definition of "earning" (the gate)

By May 30 we want at least one of:
- A real deal surfaced by AACE that you bought-low-sold-high for net profit ≥ $20, OR
- A documented case where AACE flagged a deal you converted that you would have missed, OR
- A data-backed thesis ("category X on source Y has avg N% margin, validated over Z opportunities") that justifies a money-on-the-line trade in week 3.

If none by May 30 → the loop works but scoring/thresholds need work. Plan an iteration sprint; don't claim false victory.
