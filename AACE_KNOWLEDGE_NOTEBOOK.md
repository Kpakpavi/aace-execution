# AACE Knowledge Base for NotebookLM

> **How to use this file:**
> 1. Upload this `.md` file as a Source in NotebookLM (notebooklm.google.com).
> 2. Ask NotebookLM to generate a presentation, summary, FAQ, briefing doc, etc.
> 3. To keep this up-to-date in future sessions, ask Claude to "update the AACE_KNOWLEDGE_NOTEBOOK.md with today's progress" — the structure is stable, so updates can be localized to specific sections.
>
> Last updated: end of sprint that delivered first real arbitrage end-to-end.

---

## 1. Project Identity

**Name:** AACE — Autonomous Arbitrage Commerce Engine
**Tagline:** A push-alert engine that finds the same product on different deal sites at different prices and ships scored arbitrage opportunities to an external AI agent automatically.
**Owner:** Ahlonko Kpakpavi
**Public repo:** https://github.com/Kpakpavi/aace-execution (MIT licensed)
**Type:** Operator-facing automation tool (NOT a consumer search app)
**Status:** Code feature-complete, end-to-end loop proven on real production data.

---

## 2. One-Sentence Definition

AACE pulls live deals from multiple deal-aggregator sites every 30 minutes, finds the same product across sources using token-set + Jaccard similarity matching, scores the price spread, and ships scored arbitrage opportunities to an external AI agent via HMAC-SHA256 signed webhook.

---

## 3. The Three Pillars

1. **Multi-source by design** — 4 live deal-aggregator feeds running in parallel (Slickdeals, DealNews, Ben's Bargains, TechBargains). Plug-in connector architecture makes adding new sources ~50 lines of code.
2. **Fully automated** — APScheduler tick every 30 minutes. Runs unattended on a server. Token+Jaccard matcher pairs products across sites. Price-spread scorer ranks them with configurable thresholds.
3. **Push-alerting** — HMAC-SHA256 signed POST to your AI agent on every match above the score threshold. Exponential backoff retry, 24-hour deduplication, and Postgres audit trail built in.

---

## 4. Architecture — End-to-End Flow (8 stages)

Every 30 minutes:

1. **FETCH** — Worker pulls 4 RSS feeds in parallel
2. **NORMALIZE** — Parse titles, extract prices (regex), construct NormalizedListing
3. **MATCH** — Token-set + Jaccard similarity (default threshold 0.6) clusters same product across sources
4. **SCORE** — Price spread calculation, must meet ≥$5 absolute AND ≥5% percent thresholds
5. **SIGN** — HMAC-SHA256 hex digest of canonical JSON body using AGENT_WEBHOOK_SECRET
6. **POST** — Send to AGENT_WEBHOOK_URL with `X-AACE-Signature` header
7. **PERSIST** — Write to Postgres `worker_opportunities` table for dashboard
8. **ALERT** — AI agent verifies signature, notifies user via its own channels (Slack, SMS, email, call)

---

## 5. Active Connectors

| Connector | Feed URL | Deals per tick | Status |
|---|---|---|---|
| Slickdeals | `https://slickdeals.net/newsearch.php?mode=frontpage&searcharea=deals&searchin=first&rss=1` | ~24 | Live |
| DealNews | `https://www.dealnews.com/?rss=1&sort=time` | ~50 | Live |
| Ben's Bargains | `http://bensbargains.net/rss/` (redirects to `https://bensbargains.com/rss/`) | ~20 | Live |
| TechBargains | `https://www.techbargains.com/rss.xml` | ~200 | Live |
| Reddit | `https://www.reddit.com/r/{subs}/new.json` | n/a | **Shelved — needs OAuth (anti-bot 403 on unauthenticated requests)** |

Total per tick: **~290 deals fetched**.

---

## 6. Today's Progress (8 wins)

1. **Smarter cross-source matching shipped** — Replaced exact title matching with token-set + Jaccard similarity. Same product clusters across sites even when wording differs.
2. **TechBargains added as 4th live source** — Total ~290 deals fetched per tick.
3. **Worker output wired to dashboard** — New Postgres `worker_opportunities` table + `/worker-opportunities` API endpoint + "Live Worker Output" Streamlit panel.
4. **"All Live Deals" search panel built** — Browse all ~290 live deals with a search box. Multi-source deal browser added to dashboard.
5. **Sentry error tracking added** — Opt-in production observability via `SENTRY_DSN` env var. Alerts on crashes once deployed.
6. **README polished + GitHub Actions CI** — Public repo professionally formatted. 540+ tests run on every push and PR.
7. **First real arbitrage delivered end-to-end** — Apple Watch Series 11 GPS Smartwatch, Ben's Bargains $254 vs TechBargains $329 — $75 spread (22.8%), score 0.46, HMAC-signed POST → HTTP 200 OK.
8. **4-container stack live on MacBook** — Postgres + API + dashboard + scheduled worker, all running locally as temporary VPS substitute.

---

## 7. Proof of Life — The First Real Arbitrage

| Metric | Value |
|---|---|
| Product | Apple Watch Series 11 GPS Smartwatch |
| Source A | Ben's Bargains |
| Source A price | $254 |
| Source B | TechBargains |
| Source B price | $329 |
| Absolute spread | $75 |
| Percent spread | 22.8% |
| Score (0–1) | 0.46 |
| Webhook HTTP status | 200 OK |
| Delivery attempts | 1 (succeeded on first try) |
| Detected at | 2026-06-02 00:57 UTC |

**Why this matters:** The full pipeline (fetch → match → score → sign → POST → agent receives) fired end-to-end on real production data from real RSS feeds. The system works.

---

## 8. Competitive Landscape (12 tools)

| Tool | What it does | Target user | Pricing | Comparison to AACE |
|---|---|---|---|---|
| Tactical Arbitrage | Amazon FBA arbitrage scanner; matches products across retailers | Amazon resellers | $59-129/month | Closest paid equivalent. Amazon-only; AACE is multi-source and free. |
| Keepa | Amazon price + sales-rank history; price-drop alerts | Amazon shoppers / resellers | Free or $20/month | Amazon-only, single source. AACE is multi-source cross-comparison. |
| CamelCamelCamel | Amazon price tracker with email alerts on drops | Consumer shoppers | Free | Amazon-only, single source, no cross-site arbitrage detection. |
| BrickSeek | Walmart/Target/Best Buy in-store inventory + price intel | In-store arbitrage hunters | Free / $40/mo | Different vector (physical stores). AACE is online-only. |
| Slickdeals | Community-curated frontpage deals + alerts | Consumer deal hunters | Free | AACE consumes Slickdeals as one of its 4 input feeds. |
| DealNews | Editorially curated deals across retailers | Consumer deal hunters | Free | AACE consumes DealNews as an input feed. |
| Honey / Capital One Shopping | Browser extension that auto-applies coupons + price-compare at Amazon checkout | Consumer shoppers | Free | Coupon focus at checkout, not arbitrage detection. |
| Rakuten | Cashback when you buy through their links | Consumer shoppers | Free (affiliate cut) | Different business model. Cashback after purchase, not opportunity detection. |
| Profit Bandit / Scoutify | Mobile app for scanning books/items in-store for resale | Used-book / thrift arbitrage | $10-20/month | Physical scanning workflow. AACE is automated feed-based. |
| AURA Repricer | Automated price adjustment for FBA sellers | Amazon FBA sellers | $97/month | Repricing existing inventory, not finding new opportunities. |
| Zapier + IFTTT (DIY) | Generic workflow automation; build RSS → alert flows manually | Tinkerers | Free / $20/month | What AACE would be without its matcher and scorer logic. |
| Google Shopping | Search box that compares prices across retailers | Consumer shoppers | Free | Pull-based search; AACE is push-based monitoring. |

---

## 9. Where AACE Wins — Four Differentiators

1. **Multi-source by design** — Every competitor watches one site (Amazon, in-store, single feed). AACE watches many in parallel and finds price gaps BETWEEN them. That's a different problem class. (Tactical Arbitrage, Keepa, CamelCamelCamel are all single-source.)

2. **Open source + free** — MIT licensed on GitHub. $0 recurring cost beyond infrastructure (currently $0 running on a Mac). Anyone can audit, fork, extend. (Tactical Arbitrage = $59-129/mo; AURA = $97/mo; Profit Bandit = $10-20/mo.)

3. **Operator-automated** — Push-alerts to an external AI agent via signed webhook. Built to be run by a person doing arbitrage, not browsed by a shopper. (Honey, Slickdeals, DealNews, Google Shopping are all consumer browse-first.)

4. **Extensible connector layer** — Adding a new source is ~50 lines of code + tests. Reddit code already exists (shelved pending OAuth). Generic scraper next; eBay/Keepa/Best Buy planned. (Most competitors are closed boxes — what they watch is what you get.)

**No competitor checks all four boxes simultaneously.** That is AACE's market niche.

---

## 10. Strategy to Become #1 in the Market (Three Plays)

### Play 1: Source Breadth — the Moat
**Why:** Every additional source compounds match probability. Going from 4 → 10 sources turns AACE into the single most-comprehensive arbitrage scanner available, paid or free.
**Actions:**
- Add eBay Browse API (sold comps are the gold standard for true-market baselines)
- Add Amazon via Keepa (price history + drop alerts, $20/mo subscription)
- Reactivate Reddit via OAuth (already coded, just needs credentials)
- Generic YAML scraper for Walmart, Target, Newegg, Costco, Best Buy

### Play 2: Smarter Matching — Fewer False Positives
**Why:** Today's token+Jaccard catches obvious cross-source matches but lets brand confusion through. Example caught today: Wyze cordless stick vacuum and Dyson cordless stick vacuum both matched because they share "cordless", "stick", "vacuum" tokens. Brand/model weighting + UPC/GTIN extraction stops that.
**Actions:**
- Brand and model-number weighting in similarity score
- Extract canonical product identifiers (UPC, GTIN, ASIN) where available
- Confidence score that tells the AI agent how sure we are about each match

### Play 3: Polished Product Surface — Capture Users
**Why:** AACE today is an operator engine. To get attention and lock in market position, surface it as a hosted tool with a clean UI. The "All Live Deals" panel built today is step one toward this.
**Actions:**
- Hosted-tier dashboard at a public domain (subscription or freemium model)
- Watchlist feature: alert me when this specific product drops
- Public deal feed (read-only API) for SEO and developer adoption

---

## 11. Current Challenges (Operational, Not Code)

1. **AI agent webhook URL still test sandbox** — Signed POSTs go to webhook.site instead of the real AI agent. Until swapped, the system is testing, not earning. **Blocks real alerts.**
2. **Score threshold not tuned against real data** — Default $5 / 5% thresholds were picked theoretically. Need 24 hours of live data to calibrate against actual noise levels. **Blocks production quality.**
3. **Real VPS not yet provisioned** — Currently running on a MacBook. Pauses when laptop closes or sleeps. Need a $0-7/mo cloud server for true 24/7 operation. **Blocks continuous uptime.**
4. **Product direction not yet committed** — Three viable paths (operator arbitrage / consumer search / hybrid). Cannot fully market-position until decided. **Blocks long-term roadmap.**

---

## 12. Three Approvals Needed from Manager

### Approval 1 — Path Direction
Pick a product direction so we can position long-term:
- **A.** Finish AACE as operator arbitrage bot (lowest risk, already 95% done)
- **B.** Pivot to consumer search app (2-4 week restart)
- **C.** Hybrid: keep AACE + add search UX (1-2 week add — partially built already with "All Live Deals" panel)

### Approval 2 — VPS Budget
Pick a server tier so AACE runs 24/7 instead of when the Mac is awake:
- **Free option:** Oracle Cloud Free Tier ($0/month forever, slightly more setup work)
- **Paid option:** Hetzner Cloud (~€4/month, simpler setup, faster verification)
- **Wait option:** Defer for 1-2 weeks, run on Mac in the meantime

### Approval 3 — AI Agent Webhook URL
Tell us where to POST scored opportunities so they actually reach a human:
- Provide the agent's inbound webhook URL directly, OR
- Designate someone on the agent team to provide it

---

## 13. Roadmap — 30/60/90 Days from Approvals

### 30 Days: v0.1 Ship
- Deploy to chosen VPS
- Point webhook at real AI agent URL
- 24-hour shakedown to tune scoring threshold against real data
- First real arbitrage acted on (the earn gate)
- Tag v0.1.0 release on GitHub

### 60 Days: v0.2 Breadth
- Reactivate Reddit via OAuth (3rd active source restored)
- Add eBay Browse + sold comps connector (4th paid-API source)
- Smarter matching: brand and model-number weighting
- Sentry + dashboard polish + alert-outcome tracking

### 90 Days: v1.0 Scale
- Amazon via Keepa, Best Buy, Walmart / Target scraper connectors
- Hosted public dashboard (early-access tier)
- Watchlist feature: alert me when specific product X drops
- International + resale sources (AliExpress, StockX, Mercari)

---

## 14. Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Web framework (API) | FastAPI |
| Dashboard | Streamlit |
| Database | PostgreSQL 17 |
| Job scheduler | APScheduler (BlockingScheduler) |
| HTTP client | httpx |
| RSS parsing | feedparser |
| Test framework | pytest (540+ tests) |
| Lint | ruff |
| Dep management | uv |
| Containerization | Docker + Docker Compose (4 services) |
| CI | GitHub Actions (runs on every push and PR) |
| Error tracking | Sentry (optional, opt-in) |
| Webhook security | HMAC-SHA256 signing, `X-AACE-Signature` header |

---

## 15. Key Metrics (as of last session)

| Metric | Value |
|---|---|
| Total commits in current sprint | 12+ |
| Tests passing in CI | 540+ |
| CI status | Green on every push |
| Live deal sources active | 4 |
| Deals fetched per tick | ~290 |
| Tick interval | 30 minutes |
| Real arbitrage delivered today | 1 (Apple Watch S11) |
| Webhook deliveries today | 1 (HTTP 200) |
| Recurring infra cost current | $0 (Mac is the temporary host) |
| Recurring infra cost projected | $0–7/month (Oracle Free or Hetzner) |

---

## 16. Operational Commands

```bash
# Bring up the full stack
cd ~/Claude_Projects
docker compose up -d --build

# Watch worker activity
docker compose logs -f worker

# Restart worker after env change
docker compose up -d worker

# Nuke postgres + reinit (loses dashboard history)
docker compose down -v && docker compose up -d --build

# Run tests locally (no Docker needed)
cd ~/Claude_Projects/aace-execution
uv sync
uv run pytest -v
uv run ruff check src tests

# Local one-shot smoke test
uv run python scripts/local_demo.py
```

---

## 17. Bottom Line Summary

Technical loop is proven on real data. Code is feature-complete. Only operational gates remain. Once VPS is provisioned and webhook URL is swapped to the real agent, expect first real earning within 1–2 days of shakedown.

The market has no other tool that combines:
1. Multi-source coverage
2. Open-source + free
3. Operator-focused automation
4. Extensible connector architecture

Closest paid equivalent (Tactical Arbitrage at $59-129/month) is Amazon-only. AACE wins by being broader, cheaper, and customizable.

---

## 18. Suggested NotebookLM Prompts

After uploading this document, try:

- "Create a 12-slide investor pitch deck from this content."
- "Generate a one-page executive briefing for my manager."
- "Build a presentation script I can read aloud during a demo."
- "Make a FAQ for someone hearing about AACE for the first time."
- "Compare AACE to its three closest paid competitors in detail."
- "Draft a LinkedIn announcement post for v0.1.0 launch."
- "Write a 90-second elevator pitch."
- "Generate a study guide / glossary of key terms for new team members."

---

## How to Update This Document for Future Sessions

When asking Claude to refresh this file, point at specific sections:
- **Section 6 (Today's Progress)** — replace with the new sprint's wins
- **Section 7 (Proof of Life)** — update with latest delivered arbitrage stats
- **Section 11 (Challenges)** — mark resolved items, add new blockers
- **Section 12 (Approvals)** — remove approved items, add new asks
- **Section 13 (Roadmap)** — shift completed phase, add new outer phase
- **Section 15 (Key Metrics)** — refresh counts (commits, tests, deals, deliveries)

The rest (project identity, architecture, competitors, differentiators, tech stack) is stable and rarely needs changing.
