---
name: openreview-import
description: Import a paper into Paper Tracker from an OpenReview forum link (e.g. a reviewer-console link like openreview.net/forum?id=...) when the app's built-in OpenReview fetch fails - which it does for in-review/anonymous submissions, since both the OpenReview API and the Semantic Scholar fallback it uses only cover public/indexed papers. Extracts title, abstract, anonymized authors, and venue from either an automatic fetch or page content the user pastes, then adds the paper via the existing Add Paper form. Trigger on "openreview.net" links, "import from openreview", "openreview failed/blocked", or the user offering to paste an OpenReview page.
---

# OpenReview import workaround

Paper Tracker's built-in OpenReview import (`/papers/fetch-arxiv` → `_fetch_openreview`
in `app/main.py`, backed by `app/openreview.py`) tries the OpenReview API, then falls
back to Semantic Scholar. Both require the paper to be public/indexed. A paper the
user is reviewing - under review, authors anonymized, not yet indexed anywhere - will
fail both, land in `/pending`, and show an empty manual-entry form. This skill
replaces that dead end: extract the metadata yourself (by fetching or from pasted
page text) and fill in the real manual-entry form.

## 1. Get the OpenReview ID and venue hint from the URL alone

Given a link like:
```
https://openreview.net/forum?id=b6sqtFuUwe&referrer=%5BReviewers+Console%5D%28%2Fgroup%3Fid%3DICLR.cc%2F2027%2FConference%2FReviewers%23assigned-submissions%29
```

- The `id` query param is the OpenReview ID (`b6sqtFuUwe`). Ignore everything else
  in the query string - the regex the app itself uses
  (`openreview\.net/forum\?id=([a-zA-Z0-9_-]+)`) stops at the first `&`, so you don't
  need to strip it by hand.
- Canonical URLs: `https://openreview.net/forum?id=<id>` and
  `https://openreview.net/pdf?id=<id>`.
- URL-decode the `referrer` param if present - it often encodes a venue group id you
  can read directly without ever loading the page, e.g.
  `[Reviewers Console](/group?id=ICLR.cc/2027/Conference/Reviewers#assigned-submissions)`
  tells you the venue is **ICLR 2027 Conference** and that this is a reviewer
  (in-review) context. Treat this as a strong hint for the venue field, to be
  confirmed once you see the actual page.

## 2. Try to get the page content yourself first

Attempt `WebFetch` on the forum URL. Reviewer-console pages usually require the
user's authenticated OpenReview session, so expect this to frequently return a
login wall, a mostly-empty shell, or a CAPTCHA page rather than the real content -
that's normal, not a bug to troubleshoot. If the fetched content doesn't contain a
real title/abstract, don't retry it - move to step 3 immediately.

## 3. If that fails, ask the user to paste the page

Ask them to open the link in their own browser (where they're already logged in)
and paste the visible page text - title, abstract, author list area, and the
venue/track line are all that's needed. Then wait for the paste; don't block on
anything else.

## 4. Extract the fields

From whatever text you have (fetched or pasted), extract:

- **title** - verbatim.
- **abstract** - the full abstract paragraph, verbatim.
- **authors** - OpenReview shows literal `Anonymous` (sometimes `Anonymous1`,
  `Anonymous2`, ...) for blind-reviewed submissions. If that's what's shown, set
  the authors field to exactly `Anonymous` - never invent or guess real names. Only
  use real names if they're actually printed on the page (e.g. the paper has since
  been de-anonymized/accepted).
- **venue** - build a short human string, e.g. `ICLR 2027 Conference (Under Review)`.
  Use the real venue/track name from the page if visible; otherwise fall back to the
  hint decoded from the `referrer` param in step 1. Append `(Under Review)` whenever
  the page is clearly a reviewer/discussion view rather than a published listing
  (no decision/acceptance shown) - drop that suffix if the paper shows as accepted.
- **openreview_id**, **url**, **pdf_url** - from step 1.

If the venue or anything else is genuinely ambiguous, ask rather than guess - but
don't block on fields that don't matter much (e.g. keywords).

## 5. Confirm before touching the app

Show the user the extracted title/abstract (can be truncated for display)/authors/venue
and get an explicit go-ahead before filling or submitting anything - this is a form
submission, which always needs confirmation regardless of whose data it is.

## 6. Add the paper via the browser

Load the `claude-in-chrome` skill, then on the Paper Tracker **Add Paper** page
(`/add`):

1. Type the forum URL into the "Import from arXiv or OpenReview" input
   (`name="url_or_id"`) and click **Fetch**. This runs the real
   `/papers/fetch-arxiv` flow; it will fail exactly as it does today, which is
   expected - what you actually want from it is the pre-filled hidden fields
   (`source=OPENREVIEW`, `openreview_id`, `url`, `pdf_url`) that appear in the
   manual-entry form underneath, plus it logs the attempt to `/pending` like any
   other failed fetch (harmless, consistent with existing behavior).
2. Fill in the now-visible fields with your extracted values:
   `#title`, `#authors` (comma-separated - just `Anonymous` is fine), `#abstract`,
   `#venue_year`. Leave `#status` as `Planned` and `#category_id` unset unless the
   user asks otherwise.
3. Leave the hidden `openreview_venue` field as-is (empty) - it only feeds a cosmetic
   badge on the edit page; `venue_year` is what actually shows up everywhere else.
4. After the step-5 confirmation, click **Save Paper**.
5. Report back the paper's title and a link to it (or the error, if `/papers`
   rejects it - e.g. a duplicate `openreview_id`).

### If the Chrome extension isn't connected

Don't block on it. Instead, just hand the user the extracted fields in a clean,
ready-to-paste block (title / authors / abstract / venue / URL) so they can paste
them into the Add Paper form themselves in under a minute.
