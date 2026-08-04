# SPEC — TreasureIQ: chat-first citizen interface

    run_id:        chat-first-mvp
    phase:         brainstorm (1) — done
    created:       2026-08-02
    base_commit:   e23ca3e
    deadline:      2026-08-14 23:59 (Civic Hackathon submission)
    map:           .kapi/discover/codebase-map.md
    ambiguity:     0.12 (goal 0.1 · scope 0.15 · constraints 0.1 · acceptance 0.15)

## Problem

TreasureIQ today proves its thesis (public data is not machine-interrogable) through two
expert pages: `/opportunita` (three-valued verdicts over 32 Albano `servizi`) and `/dati`
(Data Readiness Score). Both are correct and demoable. Neither is what a citizen would use.

The product as conceived is **a chat**: a citizen arrives, asks in plain Italian ("ho la
bolletta troppo alta", "ci sono bandi per informatici in scadenza?"), and the system either
answers from public data or says precisely why it cannot. Login is not the entry point —
it is an escalation, requested only when identity would change the answer.

Two gaps block that, both discovered during this brainstorm:

1. **No chat exists.** The web client is two static-ish pages.
2. **The data needed to answer those questions is not ingested.** Albano's WP REST exposes
   only `posts`, `pages`, `servizi`, `pnrr`, `unita_organizzative` — there is **no `bandi`
   or `concorsi` post type**. Bandi, concorsi and volontariato live as ordinary WordPress
   **pages**: prose HTML, zero CMB2 typed fields. Measured counts (`?search=`):
   `bando` 10 pages / 2 servizi · `concorso` 4 / 0 · `volontariato` 6 / 0 ·
   `contributo` 26 / 6 · `avviso pubblico` 17 / 2 · `borsa` 0 / 2.

Consequence: `extract/llm.py` — dead code per the map (§7d), imported by nothing — becomes
load-bearing. Prose pages can only yield structured requirements through quote-gated LLM
extraction. The project's headline anti-hallucination defence stops being decorative.

## Goal

Ship, by 2026-08-14, a ≤3-minute video demonstrating a working chat over Albano public data,
where the citizen's question is answered by a deterministic engine and the model never
decides eligibility. Repo stays public, OSS, and honest about what it does.

## Scope

IN:
- Chat UI as the front door of the web client (Google-like: centred input, warm, accessible,
  short motto, footer). Anonymous by default.
- Runtime LLM (local, Ollama) doing exactly two jobs: intent+slot extraction from NL, and
  verbalisation of engine output. Never verdicts, never new facts.
- Ingestion of Albano `pages` matching bando|avviso|concorso|volontariato|contributo|borsa,
  deduped against `servizi`, through the quote-gated extractor.
- Wiring `extract/llm.py` into the ingestion path behind an `LLMProvider` abstraction.
- Readiness cards for Genzano / Ariccia / Marino at score zero, each with its own diagnosis.
- SPID/CIE escalation, mocked, triggered only when an UNKNOWN_PROFILE criterion is decisive.
- The two-line CORS fix (see D-10).

OUT (explicitly not built):
- inPA, Gazzetta Ufficiale 4ª serie speciale, RUNTS connectors. Named in the video as
  studied future directions only.
- HTML scraping of Genzano / Ariccia / Marino.
- Real SPID/CIE integration (requires accreditation).
- Abuse protection / rate limiting (Cloudflare) — see DEFERRED.
- Replacing `/opportunita` and `/dati`. They stay, as the expert view behind the chat.

## Verified facts (probed 2026-08-02, not assumed)

    Albano   comune.albanolaziale.rm.it   WP REST live. Types: posts, pages, servizi,
                                          pnrr, unita_organizzative. No bandi/concorsi type.
    Genzano  www.comune.genzanodiroma.roma.it   200 · Drupal + Halley · /wp-json → 404
    Ariccia  comune.ariccia.rm.it/it            410 Gone on /wp-json and /it/wp-json
                                                 (WordPress with REST deliberately disabled)
    Marino   comune.marino.rm.it/it             200 on every path, body is always
                                                 <body onload="window.open('.../homepage.html')">
                                                 — entire site is a JS redirect stub

Marino returning 200 on `/wp-json/wp/v2/servizi` while serving a redirect stub is a demo
asset: naive uptime monitoring would score it healthy. Three adjacent comuni, three distinct
failure modes — proprietary CMS, API switched off, site that is a redirect.

Semgrep (1.172.0, rulesets p/python p/flask p/javascript p/typescript p/react p/secrets
p/dockerfile p/security-audit, 332 rules, 30 files, ~100% parsed): **0 findings**. The
`TREASUREIQ_SECRET` demo default did not fire (low-entropy plain string, no rule matches).
The session-cookie and CORS concerns in map §7a-b are invisible to static rules by design —
zero findings is not a clearance for them.

## DECISIONS

- **D-01 — The model never decides.** Verdicts come from `match/engine.py` only. The runtime
  model does intent+slot extraction and verbalisation, nothing else. Guardrail: the response
  is assembled from record fields; the model rephrases, it does not add facts.
  *Why:* this is the project's founding thesis. A model that guesses eligibility makes
  TreasureIQ into the thing it argues against.

- **D-02 — Chat is the front door, not a replacement.** `/opportunita` and `/dati` remain
  reachable and unchanged as the expert view.
  *Why:* premortem — if the local model underwhelms on video, there is still a finished
  product behind it. Removes the single-point-of-failure shape.

- **D-03 — Second data source is Albano `pages`, not a new portal.** No inPA, no Gazzetta,
  no scraping of neighbouring comuni.
  *Why:* one source, no new connector to invent, and the pages are exactly where bandi /
  concorsi / volontariato actually live. Fits 12 days.

- **D-04 — `extract/llm.py` gets wired in, at ingestion time only.** Extraction runs offline,
  results cached to `data/extraction-cache/` (versioned, diffable) and committed. No
  extraction call happens while a citizen is waiting.
  *Why:* moves the risky operation out of the demo path. On video, the data is already
  extracted and reviewable.

- **D-05 — Quote-gating is mandatory and non-negotiable.** A requirement field is populated
  only if the model returns the verbatim source sentence it derives from. No quote → field
  stays `None` → engine reports UNKNOWN_SOURCE.
  *Why:* `None` means "the source did not state this", never "unconstrained". Silent
  invention would corrupt the one guarantee the project sells. Also bounds the
  prompt-injection surface from ingested third-party content.

- **D-06 — Ollama + Qwen local, both for ingestion extraction and runtime.** Anthropic is
  the fallback, switched in if the spike (D-07) shows an unacceptable discard rate.
  *Why:* user decision — save token budget for development; privacy narrative ("citizen data
  never leaves the machine") holds end-to-end; whole system demonstrably runs on a laptop.

- **D-07 — Measurement spike gates the plan.** Before any chat code: run the quote-gated
  extractor with Qwen over 15 Albano pages, count fields populated vs discarded.
  Threshold: if <40% of pages yield at least one gated requirement, switch ingestion to
  Anthropic immediately — not "later, once the code is fixed".
  *Why:* blind spot — the entire plan rests on a discard rate nobody has measured. Finding
  out on day 9 is fatal; on day 2 it costs nothing.

- **D-08 — `LLMProvider` abstraction is written regardless.** One interface, `ollama` default,
  `anthropic` fallback, selected by env.
  *Why:* the switch in D-07 must be a config change, not a refactor under deadline.

- **D-09 — Identity is asked for only when it is decisive.** SPID/CIE escalation fires when a
  criterion is UNKNOWN_PROFILE *and* resolving it would change the verdict. Anonymous users
  get generic answers plus URP / office contact references.
  *Why:* data minimisation made visible — a strong civic argument, and it falls straight out
  of the existing three-valued engine. Mocked, as today.

- **D-10 — CORS fix folded in, not deferred.** `api/treasureiq/api.py:81-83`: `.strip()` each
  origin (today `"a, b"` silently yields the non-matching origin `" b"`), and add `DELETE` to
  `allow_methods` (`web/lib/api.ts` issues `DELETE /api/session` for logout; preflight fails
  cross-origin today).
  *Why:* real correctness bugs, two lines, found by hand — semgrep cannot see either.

- **D-11 — Video is shot on day 8 (≈2026-08-10), with a gate on day 6.** If on day 6 the chat
  cannot carry one end-to-end conversation, the video is shot on the existing pages and the
  chat appears as a short sequence.
  *Why:* premortem — the most likely failure is a chat that is perpetually "almost ready"
  while the only mandatory deliverable goes unshot.

## AMENDMENTS (post-wave-1, 2026-08-02)

- **D-12 — `national_catalogue` becomes a live measurement, folded into B7.** `readiness.py`
  scores this dimension (weight 10) off a hardcoded `datasets_on_dati_gov: 0` (`api.py:63-65`)
  — an assertion, not a measurement. `dati.gov.it` runs a working CKAN API at
  **`/opendata/api/3/action/package_search`** (note the `/opendata` prefix; plain `/api/3/`
  404s). Query `holder_name:"Comune di X"` per comune, record count + timestamp.
  Measured 2026-08-02, national catalogue = 65 767 datasets:

  | holder | datasets |
  |---|---|
  | Regione Lazio | 502 |
  | Roma Capitale | 361 (holder names carry an `- AREA TEMATICA: …` suffix, so exact-match on `"Roma Capitale"` returns 0 — use fuzzy) |
  | Città metropolitana di Roma Capitale | 0 |
  | Comune di Albano Laziale · Ariccia · Genzano di Roma · Marino | 0 |

  *Why:* the chain breaks below the regional level — that is a measured fact, not a claim, and
  it costs one API call per comune. Extends B7 (same files: `readiness.py`, `api.py`,
  `dati/page.tsx`), so no new brief and no file conflict. Not a new *opportunity* source, so
  it does not reopen the inPA/Gazzetta/RUNTS exclusion.

- **D-13 — no new standard, confirmed against the evidence.** AGID's **DCAT-AP_IT** already
  exists and `dati.gov.it` implements it. DCAT describes the *container* (title, publisher,
  licence, distribution), never the *content* — there is no national vocabulary for a bando's
  eligibility criteria. Perfect DCAT-AP_IT compliance would still not tell a citizen whether
  they qualify. TreasureIQ measures the distance between what is published and what is asked;
  it does not propose a competing vocabulary.

- **D-14 — D-07 verdict revised to GO on Ollama.** See `.kapi/spike-d07.md` addendum: Qwen
  extracted from 4 pages against a ceiling of 3 pages containing any eligibility signal. The
  26.7% measured corpus emptiness, not model capability. Threshold denominator redefined to
  *pages containing an eligibility signal*. Anthropic stays the env-only fallback (D-08); no
  A/B was run (`ANTHROPIC_API_KEY` absent, SDK not installed) and none is warranted.

- **D-15 — PDF attachments get parsed, not just flagged.** 9 of 15 sampled pages link PDFs and
  that is where the eligibility criteria live (ERP: 268 body words, 19 PDFs, statutory ISEE
  thresholds absent from the page text). Probed 2026-08-02: the attachments carry a **text
  layer**, so `pypdf` suffices and no OCR is needed — the risk that argued for flag-only does
  not exist. `pypdf` lazily imported; quotes must cite the attachment (URL + page), never be
  flattened onto the page URL; hard runtime budget per B4's amendment (max 5 PDFs/page, skip
  >2 MB, ~12k char corpus cap, prefer `bando|avviso|regolament` filenames, log every skip).
  *Why:* this is the highest-value data in the project — it turns "the comune published
  nothing legible" into a demonstrated recovery of real ISEE thresholds for public housing.
  *Risk accepted:* extraction wall-clock. The spike measured 20.9 s/page on short bodies; the
  budget above exists to keep a full run in minutes rather than hours.

- **D-16 — graduated recovery ladder, and the cost of recovery becomes a published metric.**
  The system does not silently succeed or silently fail at reading a document. Every record
  lands on one of three rungs, and the rung is recorded:

  | level | condition | citizen sees |
  |---|---|---|
  | `L1_manuale` | nothing machine-readable recovered | the bando + the responsible office / URP: name, phone, email, hours. The burden stays with the citizen, stated plainly. |
  | `L2_estratto` | PDF had a text layer, ≥1 quote-gated requirement recovered | the criteria, each with its verbatim quote and source document |
  | `L3_illeggibile` | PDF exists but yields no usable text (scan, image-only, encrypted, parse failure) | same as L1 behaviourally, but recorded distinctly — this is the worst case and must not hide inside L1 |

  Alongside the rung, ingestion records what recovery **cost**: `pdfs_linked`, `pdfs_opened`,
  `pdfs_skipped` (+reason), `chars_processed`, `extraction_seconds`, `requirements_recovered`.

  *Why this matters more than the data it recovers:* it converts our engineering effort into a
  measurement of the disservice. TreasureIQ stops asking only *is it published?* and starts
  answering *what does it cost to find out?* — a number produced by a real run, not an opinion.
  "This comune costs 47 seconds of local GPU to tell you whether you qualify for public
  housing; the Regione would answer in one query" is a defensible, reproducible claim.

  *Constraints:* instrumentation ONLY. It must never influence a verdict, a criterion state, or
  the D-05 quote-gate. Unmeasured fields are `null`, never estimated. Feeds a readiness signal
  in B7 (D-12's neighbour) rather than a new engine concept.

- **D-17 — the cost surfaces in two places, and the two costs are never conflated.**

  | cost | measures | whose failing |
  |---|---|---|
  | `recovery_*` (from ingestion, D-16) | seconds / PDFs / chars spent digging criteria out of attachments | **the comune's** — this is the openness metric |
  | `answer_seconds` (runtime) | GPU spent understanding the question and composing the reply | **ours** — plain efficiency |

  Summing them, or showing the second where the first belongs, would tell a citizen how slow
  *we* are instead of how closed *their* comune is. Keep them separately named everywhere.

  **Surface 1 — per-chat synoptic (B5 contract + B6 strip).** A one-line strip above each
  answer: what the criteria behind this answer cost to recover, against the comune average.
  A caption, not a panel; the answer stays above the fold. Hand-rolled inline SVG or CSS —
  **no chart library, no CDN** (the offline build is a project guarantee). Nulls render as
  nothing; a missing measurement must never look like a measured zero.

  **Surface 2 — global cost view in `/dati` (B7, wave 3).** Where the ranking lives.

  *Ranking caveat, decided now:* a "most / least virtuous entities" leaderboard across four
  comuni where three score zero is not a chart, it is a sentence — and padding it into one
  reads as spin, which is fatal for a project whose whole claim is honesty about data. So the
  global view has two distinct registers:
  - **Across entities (N=4 + Regione):** a plain honest table, not a bar race. Albano measured;
    Ariccia / Genzano / Marino at zero with their distinct diagnoses (D-12); Regione Lazio 502
    datasets as the level where the chain still works.
  - **Within Albano (N≈50 records):** here the real distribution lives — cost per opportunity,
    the L1/L2/L3 split, which bandi cost the most to open. This is where a chart is honest,
    because the sample supports one.

  Any chart work must load the `dataviz` skill before the first line of chart code.

- **D-18 — Fonte Nuova joins as the comparator; the province survey becomes evidence.**
  Full measurement in `.kapi/discover/survey-provincia-roma.md` (IndicePA official sites,
  2026-08-02): **20 of 119 comuni in the province of Rome expose a working `/servizi` API
  (16.8%)**, and **Albano ranks 2nd with 32**, behind Fonte Nuova's 34.

  Consequences:
  - **The thesis gets stronger and more honest.** Albano is not a cherry-picked laggard; it is
    near the top and still cannot answer a citizen's question. Frame the demo that way.
  - **Ingest Fonte Nuova for real** (`comune.fontenuova.rm.it`) as a second `SOURCES` entry —
    the WP connector is generic, so this is configuration plus one ingestion run, not new code.
    Two comuni with measured recovery cost make D-16's metric comparative instead of absolute.
  - The other 18 API-bearing comuni are a context row; the 99 without are the closing number.
  - `answer_seconds` is **dropped** from D-17: the runtime cost measures us, not the
    disservice, and it dilutes the one number the video should leave behind.
  - Halley Informatica (Ciampino, Genzano) exposing nothing across its installed base is a
    *vendor-level* finding, not a per-comune one. Say so precisely; do not generalise further
    than the two measured cases.

  *Sequencing:* B4 is mid-run on Albano. Do not widen it in flight — land Albano, verify the
  numbers, then add Fonte Nuova as a short follow-up before B7 renders the comparison.

  *Method note worth keeping:* an earlier pass that guessed domains (`comune.X.rm.it`,
  `comune.X.roma.it`) produced 24 consecutive misses and would have reported a far bleaker and
  simply wrong picture. Guessed domains are not evidence. IndicePA is the authority.

## DISCRETION (implementer's call)

- Qwen model size/variant per role (a larger instruct model for offline extraction, a smaller
  one for runtime intent, is reasonable; RAM-bound).
- Chat transport: SSE streaming vs plain POST. Streaming is nicer on video, not required.
- Slot-filling dialogue policy: how many questions before falling back to a generic answer.
- Dedup strategy between `pages` and `servizi` (`raw_hash`, URL, or title similarity).
- Exact page-selection query set beyond the six keywords already measured.
- Whether `Requirements` gains `titolo_studio` — only needed if concorsi records warrant it;
  it touches `CRITERION_CHECKS`, so skip unless the data demands it.
- Copy, motto and footer wording. Visual language follows the existing tokens in
  `web/app/globals.css` (see map §3) — no new design register.

## DEFERRED

- inPA / Gazzetta Ufficiale / RUNTS connectors — named in the video as future work.
- Abuse protection and rate limiting for anonymous chat (Cloudflare or equivalent).
- Real SPID/CIE integration.
- Session cookie hardening for production: timed/encrypted serializer, `secure=True`, set
  `TREASUREIQ_SECRET`, stop trusting client-supplied profile attributes (map §7a).
- Tests. None exist anywhere (map §4). Not shippable inside 12 days alongside the chat;
  record the debt honestly rather than pretend.
- `web/` `.dockerignore` (map §7h) and the `localhost:8000` copy error in
  `web/app/page.tsx:81` (map §7g).

## RISKS

- **R-1 (high) — Qwen discard rate too high under quote-gating.** Pages yield no structured
  requirements, "bandi per informatici" returns empty on video. → Gated by D-07 on day 2;
  fallback is D-06/D-08.
- **R-2 (high) — Chat consumes all 12 days and the video goes unshot.** → D-11 hard date and
  day-6 gate; D-02 keeps a shippable product behind it.
- **R-3 (medium) — Small local model produces mediocre Italian on camera.** → D-01 keeps
  facts in engine-generated text; the model only stitches. Verbalisation stays short.
- **R-4 (medium) — Ingested page content reaches the extractor prompt (injection pattern).**
  → D-05 discards any value lacking a verbatim quote; low hostility probability on a
  municipal site, but the mechanism is what bounds it.
- **R-5 (low) — Page/servizi duplicates inflate results.** → dedup, DISCRETION.
- **R-6 (low) — Ollama load during video recording degrades UI responsiveness.** → extraction
  is offline (D-04); only the small runtime model is live.
- **R-7 (medium, MEASURED 2026-08-02) — Ollama's grammar-constrained decoding rejects
  `Decimal` fields.** pydantic emits a lookahead regex `pattern` for `Decimal` that llama.cpp
  cannot parse; `qwen3:4b` returns HTTP 400 "failed to parse grammar" the moment such a field
  appears in a schema-constrained call. Worked around in `chat/intent.py` by typing the slot
  `float` and converting to `Decimal` when building `CitizenProfile` — the money-is-Decimal
  convention still holds everywhere the value is stored or compared, only the model boundary
  is float. **Any future schema-constrained field must avoid `Decimal`.**
- **R-8 (medium, MEASURED 2026-08-02) — topic classification quality is model-dependent.**
  `qwen3:4b` could not classify "bolletta elettrica troppo alta" from a bare enum of topic
  slugs; it defaulted to `sconosciuto` until the system prompt was extended with a per-topic
  keyword cheat-sheet generated from `TOPIC_KEYWORDS`. This is a prompt crutch compensating for
  a small model, not a guarantee — the video's example questions must be verified against the
  actual shipped model, and a topic that classifies today can regress if the model changes.
- **R-9 (high, FOUND IN REVIEW 2026-08-02) — fabricating citizen attributes.** The first B5
  implementation defaulted an anonymous user's age to 40 because `CitizenProfile.eta` was
  non-optional, which turns "I don't know your age" into a confident NOT_MET on any
  age-restricted bando and silently kills the SPID escalation for age. Sent back for revision.
  **Standing rule: an attribute the citizen did not state must reach the engine as unknown,
  never as a plausible default.** This is the mirror of D-05 — we do not invent facts about the
  source, and we do not invent facts about the person.

## Acceptance

1. A citizen can open the site, type "ho la bolletta elettrica troppo alta" in Italian, and
   receive an answer built from Albano public data with a link to the source record.
2. A question with no matching data produces "il comune non l'ha pubblicato / non l'ha
   scritto" — distinguishable, in the copy, from "non ho trovato nulla".
3. At least one conversation reaches the SPID escalation because an UNKNOWN_PROFILE criterion
   is decisive, and the chat states *why* identity is needed.
4. `/dati` shows four comuni: Albano scored, Genzano / Ariccia / Marino at zero with distinct
   diagnoses.
5. No verdict in any response originates from the model; every criterion state traces to
   `match/engine.py`.
6. Every requirement extracted from a prose page carries its source quote in the cache file.
7. A ≤3-minute video exists and is submitted before 2026-08-14 23:59.

## Residual ambiguity

- Chat conversation depth (how many turns of slot-filling before answering) is unspecified —
  DISCRETION, but it is the parameter most likely to make the video feel good or clumsy.
- Whether concorsi records need `titolo_studio` cannot be settled until the pages are
  actually extracted. Decide during execute, from data.

---

# AMENDMENTS — round 2 (2026-08-03): four citizens, two rails, one published cost

    brainstorm round 2 · 4 rounds of dialogue · ambiguity 0.11
    (goal 0.10 · scope 0.15 · constraints 0.10 · acceptance 0.10)
    Extends the run in flight (`chat-first-mvp`). Does NOT reopen D-01…D-18; where it
    touches them it says so explicitly.

## What triggered this round

Four concrete citizens, proposed as the demo's spine:

| # | citizen | question | comune |
|---|---|---|---|
| 1 | Luigi, 70 | bolletta (telefono / luce) troppo alta | Albano Laziale |
| 2 | Giada | abbonamento autobus per andare a scuola l'anno prossimo | Albano Laziale |
| 3 | Stefania | un servizio di volontariato per anziani | Albano Laziale |
| 4 | Mirella | quando ritirano il vetro | Ariccia |

Walking them against the shipped code exposed two structural gaps that D-01…D-18 do not
cover, and one measured fact that changes what the national layer can be.

## Verified facts (probed 2026-08-03, not assumed)

**F-1 — `dati.gov.it` catalogues statistics *about* measures, never the measures.**

| CKAN query | count | what is actually there |
|---|---|---|
| `bonus sociale` | 21 | Social Card beneficiary counts 2011-2012, INPS pension spend |
| `bonus elettrico` | 1 | *requests per district, Comune di Rovigo, 2018* |
| `bonus telefonico` | **0** | — |
| `calendario raccolta differenziata` | **342** | Bari publishes it per district, open format |
| `agevolazioni tariffarie` | 3 | Regione Lazio: SIRGAT, Elenco Generale Abbonamenti |

No dataset anywhere states **who is entitled to what**. The national catalogue knows how
many people obtained a benefit; it does not know whether you qualify. This is D-13 confirmed
from the opposite direction: it is not only the vocabulary that is missing, it is the content.

**F-2 — Albano coverage per scenario topic** (`X-WP-Total`, servizi/pages):
`trasporto` 2/9 · `scolastico` 4/5 · `volontariato` **0/6** · `anziani` 2/6 ·
`rifiuti` 1/23 · `vetro` 0/1 · `bolletta` **0/0** · `energia` 0/9.

**F-3 — Ariccia's waste calendar is not the Comune's at all.** It lives on
`https://www.aricicla.com/calendario`, operated by **TeknoService** (private concessionaire).
Measured: Wix SPA, ~400 KB; `/calendario` and `/` return **byte-identical** responses
(399 880) — client-side routing; no `wix-warmup-data` block; zero occurrences of `vetro` or
any weekday in the server HTML; no calendar PDF (the single attachment is a `.docx` served as
`?dn=Informativa_Privacy_….pdf`). Comune API `410 Gone`. Comune datasets on dati.gov.it: **0**.
Institutional sites remain server-side HTML and scrapable: Ariccia `/it/` 200 (127 KB,
exposes `/it/menu/servizi`), Genzano 200 (~96 KB).

**F-4 — institutional links that resolve** (others considered were 404):
`https://www.agid.gov.it/it/ambiti-intervento/open-data` · `https://www.schema.gov.it/`
(national schema/ontology catalogue — this is the "standard format" to cite) ·
`https://www.dati.gov.it/`.

## DECISIONS (round 2)

- **D-19 — the router classifies the *shape* of the question before the topic. Two rails.**
  Half the scenarios are not eligibility problems: Stefania and Mirella ask *where / when /
  how*, not *am I entitled*. Today every message enters `match/engine.py` and leaves as a
  verdict with criteria — for Mirella that produces `UNKNOWN_SOURCE` on everything and the
  chat says "il Comune non l'ha pubblicato" about requirements that never existed.

      messaggio → LLM: QuestionKind {AGEVOLAZIONE | INFORMAZIONE} + Topic + slots
         ├─ AGEVOLAZIONE  → retrieval → match/engine.py → verdetto + criteri + quote   (existing)
         └─ INFORMAZIONE  → retrieval → NO verdict, NO criteria, NO SPID
                            → document + responsible office + topic coverage + cost   (new)

  The informational rail is *smaller* than the existing one, not larger: no engine, no
  criteria, no escalation. It reuses D-16's rungs unchanged.
  *Why:* it also makes `data_gap` honest for the first time — today `not_published` conflates
  *not published* with *published but unreadable*, which is the project's entire thesis.
  *Boundary (user-confirmed):* the informational rail **does extract the content** (the actual
  days, the actual address), but never presents it as authoritative — every informational
  answer carries the cost, a verification link to the source, and the office to call.

- **D-20 — the national/regional layer is hand-curated from official text, NOT from
  dati.gov.it.** F-1 settles it: the measures are not in the catalogue. 5–8 records
  (bonus sociale elettrico/gas/idrico, bonus telefonico, assegno unico, Metrebus/SIRGAT
  student fares), sourced from ARERA / INPS / Regione Lazio official text, ingested through
  the same quote-gated extractor (D-05 applies verbatim — no quote, no field).
  Each record carries `livello: nazionale | regionale | comunale`, always shown.
  *Why:* Luigi's correct answer is not municipal. Answering "il Comune non ha pubblicato" is
  true and misleading — he walks away believing nothing is owed to him when something is.
  *Why not a connector:* D-03's exclusion of inPA/Gazzetta/RUNTS stands. This is a small
  curated seed with citations, not a new ingestion source.

- **D-21 — two costs, never conflated, mirroring D-17's discipline.**

  | cost | granularity | measured at | answers |
  |---|---|---|---|
  | `integration_cost` | **per ente**, once | build time | *how do we reach this comune's data at all* |
  | `recovery_cost` (D-16, exists) | **per record** | ingestion | *what did reading this document cost* |

  Access-mode ladder — the label derives from the **mode**, never from a threshold (a
  threshold would be an opinion; the mode is a fact):

  | mode | condition | label |
  |---|---|---|
  | `M1_campo_tipizzato` | value from a structured API field | basso |
  | `M2_prosa_api` | text via API + quote-gated LLM extraction | medio |
  | `M3_allegato` | inside a PDF attachment | medio-alto |
  | `M4_connettore` | no API — bespoke HTML connector | alto |
  | `M5_nessuno` | nothing recoverable | non recuperabile |

  `M4` records its components as facts: public API absent (HTTP status, dated), connector
  LOC, number of HTML selectors, datasets on dati.gov.it, seconds. No estimates.
  Comparative benchmark, where one exists, is published alongside: *342 comuni publish the
  waste calendar as open data* (F-1). This is what keeps the ask credible rather than
  polemical — we are not demanding the impossible, we are naming what others already do.

- **D-22 — a generic HTML connector for institutional sites without an API, and its cost is
  the deliverable.** Reopens the D-03/scope exclusion on Ariccia/Genzano scraping, on one
  condition: **the connector's cost is published as a metric**, per D-21. Otherwise the
  scraper is a free patch that weakens the whole argument — "then there is no problem, you
  do it". With the cost published it becomes evidence: *a question that costs one query in
  Bari costs a bespoke connector here, and it breaks at the next restyle*.
  Best-effort, quote-gated like everything else. **No headless browser** (see D-23, DEFERRED).

- **D-23 — Mirella's answer terminates at `M5_nessuno`, and that is the strongest result in
  the demo.** Per F-3, the calendar is public, real, and unreachable: rendered client-side on
  a private contractor's Wix domain, with no open licence and no permanence guarantee — if
  TeknoService loses the contract, the information disappears. The chat states exactly that,
  links `aricicla.com` for the citizen to check themselves, gives the URP number, and offers
  the segnalazione.
  *Why not build the headless path:* it would cost days, produce a fragile result, and prove
  the wrong point. A documented, reproducible failure is worth more here than a recovered
  calendar.
  *Constraint:* we do **not** scrape `aricicla.com`. It is a third-party private domain; we
  link it and describe it, nothing more.

- **D-24 — cost sentences are composed deterministically and never pass through the model.**
  D-01 forbids the model from adding facts; it does not forbid it from adding *tone*. With
  copy that names public bodies as failing, that gap becomes real. Cost and diagnosis strings
  are built from fields and concatenated **after** `_verbalise`, never handed to it.
  *Why:* closes the one genuine hole in D-01, at the moment it starts to matter.

- **D-25 — the segnalazione form generates, it does not send.** It pre-fills the request
  text (office contact from IndicePA), opens `mailto:` plus copy-to-clipboard, and states
  plainly that the citizen sends it — with an explicit note that *in produzione il sistema
  potrebbe inoltrarla direttamente al Comune*. It cites AGID open-data guidance and
  `schema.gov.it` for the standard formats (F-4).
  An **anonymous per-comune counter** records segnalazioni generated, and is itself published:
  *N cittadini hanno chiesto a questo Comune di aprire questi dati*.
  *Why generate and not send:* a send button that logs to a file would be the single most
  damaging thing in a project whose entire claim is honesty about data. And real delivery
  means SMTP, verified addresses, bounce handling, and unsolicited mail to named public
  bodies generated by an anonymous system.

- **D-26 — publishing a cost judgement about a named public body carries three hard rules.**
  1. Every number carries its **date and method**, and is reproducible from the repo.
     A cost without a date is an opinion.
  2. The cost is **TreasureIQ's**, never the citizen's. Copy must never imply Mirella pays.
  3. Never infer a judgement about people from a cost. *"Il portale non espone X"* is not
     *"il Comune non lavora"*. This is a copy constraint, enforced by D-24's determinism.

- **D-27 — the four citizens become acceptance criteria.** See Acceptance (round 2) below.
  Expected shape per scenario:

  | citizen | rail | source | expected cost |
  |---|---|---|---|
  | Luigi | AGEVOLAZIONE | national curated (D-20) — Albano has 0/0 on `bolletta` | basso (curated) |
  | Giada | AGEVOLAZIONE | Albano `trasporto scolastico` (2/9) + Lazio SIRGAT | basso–medio |
  | Stefania | INFORMAZIONE | Albano `volontariato` 0 servizi / 6 pages | medio (M2/M3) |
  | Mirella | INFORMAZIONE | Ariccia — nothing | **non recuperabile** (M5) |

  The spread is deliberate: one cheap, one mixed, one expensive, one impossible. Four
  citizens, four rungs, one metric.

- **D-28 — generic web search as the last rung, `M6_web_aperto`, and it is OURS not the
  model's.** When every institutional source is exhausted on the INFORMAZIONE rail, we call a
  search API, take **title + URL verbatim**, and hand the citizen a link to check themselves.

      fonti istituzionali esaurite → search API (deterministica, in ingestion, in cache)
                                   → titolo + URL verbatim, MAI passati al modello
                                   → composizione deterministica (D-24) → risposta

  The model never searches, never sees the results, never summarises them. Qwen has no network
  and does not need one — tool-calling on a small local model would be the most fragile link in
  the chain, and here it is removed entirely. This is exactly what Gemini does: Google runs the
  search and injects the results; the model does not navigate.

  New rung, above `M5`:

  | mode | condition | label |
  |---|---|---|
  | `M6_web_aperto` | the information exists on the open web but in **no machine-readable institutional channel** | massimo · provenienza non verificata |

  *Provider:* Brave Search API (free tier 2 000 q/month, one key in `.secrets`), with
  self-hosted SearXNG in `compose.yml` as the no-key alternative. Not DuckDuckGo scraping
  (fragile, against ToS).

  *Why this strengthens the metric instead of diluting it:* per F-3 the Ariccia calendar is a
  Wix SPA — the search returns the **link**, never the content. We summarise nothing and
  extract nothing from a third party. And the honest sentence is sharper than silence:
  *"l'ho trovato con una ricerca generica, sul sito dell'azienda che gestisce il servizio, non
  su un canale del Comune — verificalo tu, perché non posso garantirti che sia aggiornato o
  che domani sarà ancora lì."*

  **Three non-negotiable constraints:**
  1. Web results **never pass through the model**. Title and URL verbatim from the API.
  2. Labelled **non verificato**, full URL visible, maximum 2–3 results.
  3. **Never on the AGEVOLAZIONE rail.** An eligibility criterion sourced from the open web
     would violate D-05 in substance while honouring it in form.

  *Demo constraint:* the search runs at **ingestion and is cached** (D-04). A live network call
  during the video is latency plus a failure point, and makes the demo non-reproducible.

  *Trigger discipline:* the fallback fires **only** after institutional sources are exhausted,
  and the rung reached is recorded per answer. If it fires on all four scenarios we are no
  longer measuring anything — the *spread* between the four is what carries the argument.

  *Consequence for D-23:* Mirella moves from `M5_nessuno` to `M6_web_aperto` with a real link.
  D-23's prohibition on **scraping** `aricicla.com` stands unchanged — we link it, never ingest it.

- **D-29 — the social goal is stated, and what remains on the citizen's shoulders is measured.**
  TreasureIQ exists to push public administrations to open their data so a citizen gets one
  unified, efficient answer instead of a search. A citizen who comes here rather than to Google
  comes for a single tool — and, legitimately, out of laziness. **Those ten seconds are not
  trivial to them.** Minimising citizen effort is a design constraint, not a nice-to-have.

  This corrects the framing used earlier in this brainstorm ("if Google finds it, the thesis
  weakens"). It does not. The value is not finding the link — it is **not having to look for
  it, and not having to verify it**. The four scenarios form an arc:

      link da controllare tu   →   risposta   →   risposta certa su di te
        M6_web_aperto              M1/M2              SPID/CIE (D-09)

  So a second metric, the mirror of D-16's recovery cost:

  > **`citizen_effort`** — what the answer still hands back to the citizen: a link to verify,
  > a phone call to the URP, a PDF to read, a form to fill, an office to visit. Recorded per
  > answer as a count of residual actions, never estimated.

  `recovery_cost` measures what the closed data cost **us**. `citizen_effort` measures what we
  could not take off **them**. The second is the one the citizen actually feels, and it is the
  number that goes to zero only when the data is open **and** identity resolves the criteria —
  which is precisely what SPID/CIE integration (D-09) is for, and why it belongs at the end of
  the arc rather than at the entrance.

  *Constraint (mirrors D-17):* never conflate the two, never sum them, never show one where the
  other belongs.

## RISKS (round 2)

- **R-10 (high) — public cost judgement on named public bodies.** Reputational, and at the
  edge, legal. → D-26's three rules; every figure dated, sourced and reproducible; the
  comparative benchmark (342 comuni) frames the ask as ordinary, not accusatory.
- **R-11 (medium) — a fragile HTML connector silently yields wrong data.** A selector that
  drifts returns plausible garbage. → the quote-gate (D-05) applies unchanged to connector
  output: no verbatim quote, no field. A broken selector produces nothing, never a fabrication.
- **R-12 (medium) — scope at 11 days.** Two rails + a curated national layer + a connector,
  on top of an open wave 3, with nothing committed. → D-11's day-6 gate stands unchanged;
  scenario priority order is Luigi → Mirella → Stefania → Giada (the first two carry the
  argument; Giada is the most droppable).
- **R-13 (medium) — third-party content dependency.** `aricicla.com` can change or vanish;
  our claim about it is dated and must be re-verifiable. → D-23 links rather than ingests;
  the probe method is recorded so anyone can re-run it.
- **R-15 (HIGH — the worst failure mode in the project) — a generic web search returns a wrong,
  stale or hostile result.** A 2019 calendar, the wrong comune, a lookalike site. Handing that
  to a citizen as if it were an answer is the most damaging thing TreasureIQ can do — worse than
  answering nothing, because it carries our credibility. → D-28's three constraints: verbatim
  passthrough, explicit *non verificato* label with the full URL visible, INFORMAZIONE rail only,
  never presented as an answer but always as *something for you to check*.
- **R-16 (medium) — `citizen_effort` becomes a vanity metric.** A number that only ever looks
  good is not a measurement. → it is a count of concrete residual actions (link, call, PDF,
  form, visit), recorded per answer, and it is allowed to be bad — Mirella's will be, and that
  is the point.
- **R-14 (low) — the informational rail grows a calendar engine.** Each informational service
  type invites its own schema. → D-19's boundary: extract content, but no per-service schema;
  everything stays text + quote + source + office.

## Acceptance (round 2 — additive to the seven above)

8.  Luigi's question ("ho la bolletta del telefono troppo alta", age stated, comune resolved)
    returns a national measure with `livello: nazionale`, its verbatim quote, its source, and
    a **basso** cost — never "il Comune non ha pubblicato".
9.  Mirella's question ("quando ritirano il vetro", Ariccia) reaches **`M6_web_aperto`**: the
    dated institutional diagnosis (API `410`, 0 datasets on dati.gov.it), then the
    `aricicla.com` link surfaced by the cached web-search fallback and shown as **non
    verificato** with its full URL, the URP contact, and the segnalazione form — plus the
    sentence that open data would have produced an answer instead of a link to check.
10. Stefania's question routes to the INFORMAZIONE rail: no verdict, no criteria, no SPID
    prompt anywhere in the response.
11. Every displayed cost carries its access mode, its date, and its measured components; a
    missing measurement renders as nothing, never as zero (D-16 constraint, unchanged).
12. No cost or diagnosis sentence passes through the verbalisation model (D-24) — verifiable
    by construction in the code path.
13. The segnalazione form sends nothing, says so, and increments the anonymous per-comune
    counter.
14. No web-search result reaches an AGEVOLAZIONE answer, and no web-search text passes through
    the verbalisation model — verifiable by construction in the code path (D-28).
15. Every answer records `citizen_effort` as a count of concrete residual actions, shown
    separately from `recovery_cost` and never summed with it (D-29).

## DEFERRED (round 2)

- Headless-browser rendering for JS-only municipal/concessionaire sites (`aricicla.com`).
- Real delivery of segnalazioni (SMTP, verified PEC addresses, bounce handling, anti-abuse).
- Per-service structured schemas for informational content (calendars, opening hours).
- Extending the curated national layer beyond the 5–8 records the four scenarios require.
- Connectors for the other 99 comuni in the province without an API.

## Residual ambiguity (round 2)

- The exact number of curated national records is bounded by the scenarios, not decided:
  5–8 is a budget, not a target. Settle during execute, from what Luigi and Giada need.
- Whether Giada's answer needs Regione Lazio SIRGAT ingested or a single curated record
  citing it — depends on whether the regional dataset carries eligibility text at all. Probe
  before building; a dataset of subscription counts would be F-1 all over again.

---

# AMENDMENTS — round 3 (2026-08-04): the census is the product

## What triggered this round

Two questions, asked in this order, that turned out to be the same question.

The first was operational: a citizen naming a comune we have no seed for (Trento) gets a
correct but poor answer — "not among the comuni this system knows". Could we search the
open web live instead of refusing?

The second was structural, and it is the one that matters: *how does this ever reach the
whole country?* A connector per comune is 7.896 connectors plus perpetual maintenance —
a treadmill the project loses. Connectors only for Roma and Milano leave the small comuni
uncovered, which are precisely the citizens with no alternative channel. And who reviews
what a live search brings back?

Round 3 answers both, and the answer to the second makes the first almost unnecessary.

## Verified facts (probed 2026-08-04, not assumed)

**F-5 — the unit of scale is the platform, not the comune.** `HtmlPagesConnector.__init__`
(`api/treasureiq/ingest/html_pages.py:176`) takes `base_url`, `ente`, `codice_istat`,
`listing_paths`. Nothing about Albano is compiled in. The same holds for `wp_pages.py`
against the WP REST API. TreasureIQ already has *two platform connectors*, not five comune
connectors: onboarding a comune whose portal runs a platform we already speak is a config
entry, not new code.

**F-6 — the API gives you the office and never its opening hours.** The AGID content type
`unita_organizzativa` (rest_base `unita_organizzative`) is present on both M2 portals in the
seed — 41 offices on Albano Laziale, URP among them, 32 on Fonte Nuova. But the REST record
for a single office carries only `title`, `slug`, `link`, `tipi_unita_organizzativa` and
system fields: no `content`, no `meta`, no `acf`. The hours live in the HTML of the page.
This mirrors exactly what `integration.py` already documents for IPA, which records the
institutional channel and not the counter timetable. Two public registries, the same silence,
on the same datum. It is not one comune's oversight; it is how the model is shaped.

**F-7 — a national frame is buildable today.** ISTAT's `Elenco-comuni-italiani.csv`
(7.896 comuni) joined to IPA's `amministrazioni.txt` yields **7.867 comuni with a known
institutional site (99%)**. The join is by normalised name + province because IPA carries no
ISTAT code; it needs a name-only second pass for 155 Sardinian comuni, where IPA still
records the provinces abolished in 2016 (OT, OG, VS, CI) against ISTAT's current ones. The
5 enti already in `enti.json` resolve to exactly the sites recorded there.

**F-8 — T0, measured.** Stratified sample by region, seed 2026, n=401: **383 measured, 18
portals unreachable**.

| Measure | Result |
|---|---|
| Expose the office list via API (axis A) | **15,9% ±3,7** |
| URP opening hours recoverable (axis B) | **4,2% ±2,0** |
| — among those that already have the API | 26,2% |
| — **in a typed field** | **0 of 401** |
| API present, no recognisable URP | 21 |
| URP present, hours not published | 24 |

**Zero.** Not one comune in the sample publishes its own URP opening hours in a field a
machine can read without interpreting prose.

**F-9 — censusing is cheap; ingesting is not.** 502 HTTP requests for 401 comuni, 72 seconds
at 8 workers, one request at a time per host. A national census on axis A is an afternoon.
National ingestion is years. This asymmetry is the whole of D-30.

## Decisions (round 3)

**D-30 — the census is the product; ingestion follows measurement.** TreasureIQ does not
race to scrape Italy. It measures, comune by comune, what it costs to read a datum, ingests
where that cost is low, and states the gap where it is not. The map of what is readable is
the asset; citizens' data is the by-product. A map nobody else has beats a dataset somebody
else will always have more of.

**D-31 — the unit of scale is the platform, never the comune.** No per-comune code. Adding
a comune on a known platform is configuration. Writing a new connector is justified by a
platform's frequency in the census, or by a comune's measured demand — never by its size
alone. Corollary, and it inverts the intuition: small comuni are the *easy* part, because
they adopted the standard AGID model (in many cases PNRR-funded) instead of defending a
bespoke legacy portal. Roma and Milano are the special cases.

**D-32 — amendment to D-28.** D-28 said: no network during a citizen's question. It now
reads: *no network for a comune whose data we hold; for a comune outside coverage the live
probe is the last rung, on the INFORMAZIONE rail only, and what it returns is labelled as
what it is.* The AGEVOLAZIONE rail is untouched and unreachable by live data — feeding a
search result into an eligibility verdict would violate D-01. A constraint bent in silence
is worse than a constraint amended in writing; this is the amendment.

**D-33 — two data lifecycles, two mounts.** `./data:/data:ro` stays read-only: curated
seeds are immutable at runtime and versioned by git. Runtime-acquired material goes to a
separate writable `./data-live`, outside git. The separation is enforced by the filesystem,
not by anyone's discipline. Mixing them is the real error — an unverified search result
filed among curated data *inherits the authority of curated data* without ever having
earned it, which is the exact confusion this project exists to expose.

**D-34 — promotion is about comuni, not about facts.** Nothing found by web search is ever
promoted: it stays labelled `non_verificato`, permanently, and never becomes project data.
Verification is structural, not editorial — `source_typed` plus the quote gate, evaluated by
code, identically every time. The two remaining human decisions are *which comuni to
onboard* (driven by measured demand, `make stato-dati`) and *when a platform recurs often
enough in the census to deserve a connector*. Neither grows with the number of comuni.

**D-35 — distinct absences never collapse into one.** The census enforces what D-16 states.
A portal that does not resolve is *not measured*, and leaves the denominator; it is not a
comune without an API. An office list without a recognisable URP is not a comune without
opening hours. "Not attempted" is not "absent". Every headline number travels with the
limit that produced it: axis B is attempted only where axis A succeeded, so 4,2% measures
what is reachable *by the structured route*, never what is published. The number that needs
no caveat is the zero.

## Risks (round 3)

- **R-16 — the census reads through one route and could understate openness.** A comune may
  publish hours in HTML with no API at all; axis B never asks. Mitigation: the limit is
  written into `data/censimento-t0.json` as `limite_dichiarato`, and the claim made in public
  is the typed-field zero, which no route-choice objection touches.
- **R-17 — live probing puts us on portals we do not control, during a demo.** Mitigation:
  hard timeout, one request at a time per host, cached after the first citizen pays for it,
  and a fall back to today's honest refusal when anything fails.
- **R-18 — a live answer about comune X sourced from comune Y.** `_e_di_un_altro_comune`
  filters by the ente's own host, which an uncovered comune does not have. Mitigation: for
  comuni with no ente record the host must contain the comune's normalised name, or be a
  known national body; everything else is dropped. Stricter without the ente, not looser.
- **R-19 — the ISTAT×IPA join is name-based and will silently rot.** Fusions and renames
  land as unmatched rows, not as errors. Mitigation: the merge reports coverage every run;
  a fall below 99% is a signal, not a rounding difference.

## Acceptance (round 3)

- The census reproduces, unaided, the `access_mode` assigned by hand to all 5 enti.
- Every quoted piece of evidence is verbatim and complete: an hours range is never cut
  mid-interval, and any shortening is declared with `[…]`.
- Re-running with the same seed produces the same sample.
- Unreachable portals are excluded from the denominator, and counted and reported separately.
- A citizen naming an uncovered comune is never shown another comune's data, on any rail.
- No web-search result ever reaches the AGEVOLAZIONE rail.

## Deferred (round 3)

- Full national census on axis A (feasible per F-9; sample suffices for the T0 headline).
- The merge script lives in a scratchpad, not in `ingest/` — it must move before ISTAT or
  IPA next update.
- Population data (absent from the ISTAT file used), needed to stratify by comune size
  rather than by region alone.
- `make promote` and `make stato-dati`.
