# Using Gap Analysis: "What Should I Learn Next?"

This is a walkthrough for the operator, not a code reference — see
[docs/api.md](api.md) for the full endpoint contract.

## What it's for

You're reading job postings with good compensation and seeing technologies
you don't know. This feature answers: across everything you're applying to,
what's the highest-leverage thing to learn or practice next?

Paste in job descriptions as you find them. Each one gets resolved against
your CV and skill bank into a tier report. Do that for enough postings and
the aggregate roadmap tells you which missing skill shows up most often —
that's what to learn first.

## Walkthrough

All of this requires an operator JWT (log in via the SPA, or send
`Authorization: Bearer <token>` directly).

**1. Store a posting**

```bash
curl -X POST "$API/api/v1/gaps?title=Senior%20Backend%20Engineer&company=Acme" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: text/plain" \
  --data-binary @posting.txt
```

Accepts plain text, PDF, DOCX, Markdown, or JSON — same parser as
`/api/v1/cv/tailor`. Re-posting identical text returns the existing posting
with `"duplicate": true` instead of creating a second row.

Response: `{"id": 42, "content_hash": "...", "duplicate": false}`.

**2. Analyze it**

```bash
curl -X POST "$API/api/v1/gaps/postings/42/analyze" \
  -H "Authorization: Bearer $TOKEN"
```

Returns a `GapReportOut`: every requirement the JD text mentions, resolved
into exactly one tier (below), plus `coverage` (the share you could defend
in an interview today) and `unrecognized` (see below). Re-analyzing the same
posting overwrites the previous result rather than piling up duplicates.

**3. Read it back later**

```bash
curl "$API/api/v1/gaps/postings/42" -H "Authorization: Bearer $TOKEN"
```

Same shape as step 2, minus `unrecognized` — that field is only computed
live at analyze time, not stored.

**4. Check the roadmap**

```bash
curl "$API/api/v1/gaps/roadmap" -H "Authorization: Bearer $TOKEN"
```

Every gap term across every analyzed posting, ranked by `jd_count`
descending. The first row is the answer: *"Kubernetes — wanted by 12 of 20
postings — learn this first."* Everything past the top few rows is
supporting detail.

The SPA's `/roadmap` page renders this as a table if you'd rather not use
curl.

## What the tiers mean

Every requirement a JD mentions lands in exactly one tier, ordered cheapest
to close first:

| Tier | What it means | What to do |
| --- | --- | --- |
| **covered** | On your live CV and defensible today | Nothing — already showing this to recruiters |
| **stale** | On your CV, but unused long enough it needs a refresher before an interview | Not a gap so much as a risk: a recruiter is being shown a skill you can't currently defend. Brush up before the interview, not before applying |
| **unvouched** | In your skill bank, but the trust policy is keeping it off the live CV | Cheapest fix: update your CV to claim it |
| **deferred** | You know of it, deliberately parked with a note ("promote if a GraphQL role comes up") | A decision, not studying — check the note and decide if this posting changes the calculus |
| **unknown** | The JD wants it and it's nowhere in your bank | The real "go learn it" tier — this is what the roadmap is for |

`coverage` in a report is the share of requirements in the `covered` tier —
deliberately excluding `stale`, since counting a skill you can't currently
defend would overstate your readiness.

## Growing the vocabulary (`unrecognized`)

The `unknown` tier only catches terms already listed in
`data/jd_vocabulary.json`. A brand-new technology the vocabulary has never
seen is invisible to tier resolution — it just doesn't show up anywhere,
rather than landing in `unknown`.

That's what `unrecognized` on the analyze response is for: capitalized,
technical-looking tokens from the JD that aren't in the vocabulary yet,
ranked by how often they appear. It's a suggestion list for a human, not an
automatic feed — expect noise (stray proper nouns, acronyms that aren't
skills). Skim it, and for anything real, add an entry to
`data/jd_vocabulary.json`:

```json
{
  "term": "Snowflake",
  "group_id": "data-warehousing",
  "aliases": ["snowflake db"]
}
```

Reuse an existing `group_id` from the file so the roadmap groups it
sensibly. Redeploy (or re-seed the document store) to pick up the change,
then re-analyze existing postings to backfill the new term.

Once `unrecognized` on real postings comes back mostly noise rather than
real terms, the vocabulary is complete enough — that emptiness is itself the
completion signal, not something to chase to zero.

## Continuous board monitoring (optional)

If pasting JDs by hand gets old: `/api/v1/tracked-boards` lets you register
an ATS board (Greenhouse, Lever, Ashby) for continuous monitoring, so new
postings from companies you're watching get ingested automatically instead
of copy-pasted. See [docs/api.md](api.md) for the tracked-boards contract.
