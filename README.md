# Firehose

Read the whole river; look at only what matters.

Jev scores **every** incoming item — not a sample — because at ~100ms and
$0.042 per million input tokens you can afford to. Atria then reasons and writes
about what survived. Two models, two jobs, and a chat window over the result.

```
tender boards ─┐
news feeds  ───┼─► Jev (typed, calibrated) ─► keep / review / drop ─► digest.html
               ┘                                      │
                                                      └─► agent ◄─ you, in the browser
                                                          (Atria writes, Jev looks)
```

---

## Why it is built this way

| Half | Stack | Reason |
|---|---|---|
| ingest + scoring | plain Python, stdlib only | A parallel map over items — no branches, no cycles, no carried state. A graph framework would add per-item overhead to an operation whose whole selling point is 100ms. Runs as a cron job anywhere. |
| the agent | LangGraph + `langchain-typesafe` | Chat, tools and memory genuinely are a state machine. Conversation persistence, LangSmith tracing and interrupts come for free. |
| the chat UI | Next.js + Vercel AI SDK | The SDK does streaming plumbing only. **Every component is hand-written** — no component library, no AI Elements. |

Jev is reached through the official `langchain-typesafe` package. One subclass in
`firehose/jev.py` swaps the route to `/v1/decisions` because your key is from
AI/ML API; everything else is the package unchanged.

## The idea worth stealing: confidence gating

Jev's confidence is calibrated — it correlates with accuracy — so it can be
acted on rather than displayed:

```
relevant AND confident      -> KEEP    you read these
low relevance AND confident -> DROP    never shown
anything else               -> REVIEW  the model declining to guess
```

`REVIEW` is not a weak keep. It is the band where the model isn't sure enough to
decide, which is exactly the band a human should own. Tune the three numbers in
`[gates]`.

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in AIMLAPI_API_KEY and ATRIA_API_KEY
set -a && source .env && set +a
```

**See it work with no keys at all:**

```bash
python -m firehose --config config.demo.toml --mock run --no-dedupe
open out-demo/digest.html
```

`--mock` swaps Jev for a lexical stand-in and, if `ATRIA_API_KEY` is unset, swaps
Atria for a scripted stand-in too — so the whole stack, chat window included,
runs end to end with nothing configured. Both say so on screen. It is for
checking plumbing, never for judging quality.

**Real runs:**

```bash
python -m firehose run                  # fetch, score, write out/digest.html
python -m firehose run --stream leads   # one stream only
python -m firehose chat                 # terminal chat
python -m firehose ask "what should I bid on this week?"
```

**The web chat:**

```bash
./run.sh          # bridge on :8000, UI on :3000
```

Or the two halves separately:

```bash
uvicorn firehose.server:app --port 8000
cd web && npm install && FIREHOSE_BRIDGE=http://127.0.0.1:8000 npm run dev
```

---

## Tender sources — what actually works

Researched and wired, all keyless except SAM:

| Source | Coverage | Key | Notes |
|---|---|---|---|
| **TED** | EU | none | The only one that filters CPV server-side. POST + JSON body. |
| **Find a Tender** | UK, above-threshold | none | OCDS, cursor-paginated, 429 + `Retry-After`. |
| **Contracts Finder** | UK, below-threshold | none | OCDS. **403 means throttled**, not an auth failure. |
| **SAM.gov** | US federal | free | Mandatory `postedFrom`/`postedTo` as `MM/dd/yyyy`. |

Neither UK service filters CPV server-side, so those pull a date window and
filter locally on `72xxxxxx` / `48000000`. The CPV list is in
`firehose/tenders.py` — widen it there if your work spans other families.

### Client work (stream 3)

Freelance and contract leads, from sources that are all free and keyless:
r/forhire, r/jobbit, r/slavelabour, Hacker News' monthly "Freelancer? Seeking
freelancer?" thread (searched as *comments* - that is where it lives), RemoteOK's
JSON feed, and We Work Remotely.

The rule that makes this stream work is `[gates.drop_choices]`. Boards like
r/forhire are roughly half people advertising *themselves*, and no relevance
score can separate "I need a developer" from "I am a developer" - they read
almost identically. A typed Choice can, so `posting_kind = "offering"` is dropped
outright however well it scores.

Reddit rate-limits anonymous RSS harder than the docs suggest: twelve requests
spaced 2.5s apart earned a 429 on eleven of them. Requests are now spaced 8s,
carry a descriptive User-Agent, and retry once on a 429, and the source list is
deliberately short and wide rather than long and narrow - the limit is per
request, not per result. Daily is fine; hourly is not.

Everything is age-filtered (`max_age_days`, 21 days for this stream). A
month-old "need a developer" post has already been answered. Items whose date
cannot be parsed are kept - an unknown date is not evidence of staleness.

RemoteOK and We Work Remotely were tried and removed: they list full-time
salaried roles, which the exclude text correctly rejects, so they were 60% of
the items scored and none of the keeps. The fetchers remain in `sources.py` if
you ever want a full-time stream.

### Apify, and whether it is worth it

There is an `apify` source type ready to use - point it at any actor:

```toml
{ type = "apify", actor = "apify~tweet-scraper", name = "X: hiring posts",
  input = { searchTerms = ["need a web developer", "looking for an AI developer"] } }
```

It needs `APIFY_TOKEN` in `.env`. Field mapping is configurable because every
actor emits a different shape; the defaults cover the common ones.

**It is off by default on purpose.** The free sources above cost nothing and are
where clients who are actually ready to pay tend to post. Apify runs cost money
per run, take minutes rather than milliseconds, and scraping Instagram, X or
LinkedIn runs against those platforms' terms - LinkedIn in particular pursues it.
Run the free sources for a week first, count how many real leads came out, and
only then decide whether paid scraping adds enough to justify the cost and the
risk. The plumbing will be waiting.

### India: there is no legitimate feed, and I won't pretend otherwise

- **CPPP (eprocure.gov.in)** — server-rendered HTML, ~2,700 pages of 10 rows, and
  a CAPTCHA on the search. No API, no RSS, no bulk download. The "XML upload"
  docs on that site are *inbound* — for state portals pushing data in, not a feed
  you can read.
- **GeM** — no public read API. Its bids are partly republished into CPPP, which
  puts you back at the CAPTCHA.
- **data.gov.in** — a good API with no tender dataset behind it.

Every "CPPP API" or "GeM API" you find advertised is a commercial scraper. Your
real options are: scrape and solve the CAPTCHA, pay a scraper vendor, or leave
India out of the automated fetcher and watch it manually. I would not build the
first one into a product you depend on.

If a regional or private board you use publishes RSS, add it as a normal
`{ type = "rss", ... }` source and it joins the same pipeline.

---

## The agent

Four tools. Three are ordinary lookups. The fourth is the reason this pairing is
worth more than either model alone:

**`ask_jev`** lets the agent invent a brand-new typed question at conversation
time and run it across every stored item in one batch. *"Which of these mention a
deadline inside 30 days?"* over 300 items takes about a second and costs a
fraction of a cent. You would never do that with a chat model in the loop.

Conversations persist in `state/agent.sqlite`. Each browser conversation is a
thread; the CLI takes `--thread <name>`. Set `LANGSMITH_TRACING=true` to see
every tool call and token.

---

## Scheduling

`deploy/` has a cron line, a systemd service + timer, and there's a GitHub
Actions workflow in `.github/workflows/score.yml` that runs the scorer on a
schedule and keeps the digest as an artifact. All three do the same thing; pick
whichever matches where this will live.

Dedupe (`state/seen.json`) means a scheduled run only pays for items it hasn't
seen, and a run that finds nothing new leaves the existing digest untouched
rather than replacing it with an empty one.

**Keep it daily, not hourly** — a new SAM.gov key without a SAM role is capped
near 10 requests/day.

---

## Tuning it

Almost everything lives in `config.toml`. The two strings that matter most are
each stream's `include` and `exclude` — that is what Jev judges relevance
against, so write them like a brief for a new colleague, in your own words. The
shipped `leads` stream describes generic technical-services work; **edit it to
describe what Constrivo actually sells** before trusting the output.

`[gates.demote_choices]` is the safety valve: a typed answer landing on a dead
label (an already-awarded contract, say) can never become a silent KEEP — it
drops to REVIEW.

## Cost

Jev bills input tokens only; output is free. A ~300-token item costs about
**$0.0000126** across four batched questions. A thousand items a day is roughly
**$0.40/month**. Batch questions into one call — that is where the saving is.

## What this does not do

- Jev writes nothing. Every word in the digest is assembled from typed answers,
  or written by Atria in the chat.
- No semantic dedupe — two outlets covering the same story are two items.
- `AutoModeMiddleware` from `langchain-typesafe` (Jev screening risky tool calls)
  is not wired in: it builds its own client against `api.typesafe.ai`, which an
  AI/ML key does not reach. The agent's tools are read-only, so nothing is at
  risk meanwhile. Worth adding if you get a native TypeSafe key.
- The web UI has no auth. Put it behind something before it leaves localhost.

## Layout

```
firehose/
  jev.py        Jev layer: AI/ML route subclass, mock, answer helpers
  questions.py  the typed question sets (leads / tech)
  sources.py    RSS, Atom, Hacker News, fixtures — stdlib only
  tenders.py    TED, Find a Tender, Contracts Finder, SAM.gov
  pipeline.py   fetch -> score -> gate -> rank
  report.py     the HTML digest
  corpus.py     scored items the agent reasons over
  agent.py      LangGraph + Atria + the four tools (+ the keyless demo model)
  server.py     FastAPI bridge for the web UI
  __main__.py   run / chat / ask
web/
  app/api/chat  translates the bridge's events into the AI SDK stream
  components/   Chat, Composer, ToolCard, ItemCard, Markdown, StatsBar
deploy/         cron, systemd service + timer
```
