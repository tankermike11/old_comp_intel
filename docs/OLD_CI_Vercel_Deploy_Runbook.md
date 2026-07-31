# Runbook: first live verification of the Vercel-deployed site

Use this to run and verify the monthly pipeline + Vercel deployment end to
end, whenever you're ready to pick it back up. Written because the baseline
18-month EDGAR pull already ran ($32) and a follow-up run right now would
only pick up a day or two of new filings — not worth the cost yet. Revisit
this in a few weeks once there's enough new filing activity to justify it.

## What's already done (as of this writing)

- `SEC_USER_AGENT`, `ANTHROPIC_API_KEY`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`,
  `VERCEL_PROJECT_ID` are all set as GitHub repo secrets
  (`github.com/tankermike11/old_comp_intel` → Settings → Secrets and
  variables → Actions).
- `SITE_PASSWORD` is set as a **Vercel** project environment variable
  (separate from the GitHub secrets above — read by
  `surfaces/site/middleware.js` at request time).
- `.github/workflows/monthly.yml` has the deploy steps wired in
  ("Prepare Vercel deploy config" → "Install Vercel CLI" → "Deploy site to
  Vercel"), pushed to `main`.

## Pre-flight checklist (do this first — unresolved from setup)

- [ ] **Check the Vercel project's Git integration.** If the existing Vercel
  project was created via "Import Git Repository" in the dashboard (rather
  than `vercel link`), it may be set to auto-deploy from a GitHub branch
  (Vercel dashboard → your project → **Settings → Git**). If a branch is
  connected there, disconnect it (or at minimum confirm it's *not* watching
  `main`, since `main` doesn't contain `surfaces/site/dist/` — it's
  gitignored — so an auto-deploy from `main` would build an empty/broken
  site). This repo's deploys are meant to come **only** from the
  `vercel deploy` CLI step in `monthly.yml`, not from Vercel's own git
  watching. Leaving both active isn't dangerous, just confusing — you'd see
  extra broken deployments in the Vercel dashboard next to the real ones.
- [ ] Confirm `git status` is clean and `main` is up to date
  (`git pull origin main`) before triggering anything.

## Step 1 — decide if it's worth running yet

Each run since the baseline is incremental (only filings newer than each
competitor's `last_checked` date get pulled and LLM-scored), so cost scales
with how much new filing activity has accumulated — check how long it's
been since the last run before spending on a new one. Skip straight to
"just verify Vercel deploys correctly" (Step 2, using the existing data)
if you don't want to spend on new collection yet.

## Step 2 — trigger the workflow

1. Go to `github.com/tankermike11/old_comp_intel/actions/workflows/monthly.yml`.
2. Click **"Run workflow"** (top right).
3. Leave `run_type` as `monthly` (pulls anything new since each
   competitor's `last_checked`). Only pick `baseline` if you deliberately
   want to re-pull full history (expensive, same order of cost as the
   original $32 run) — you should not need this again.
4. Click **Run workflow**.

## Step 3 — watch the run

Open the running job and watch for these steps in order:

- "Run collection + analysis pass" — this is where the SEC/Anthropic API
  cost happens. Should be fast/cheap for an incremental run.
- "Commit and push updated data" — should show a real commit if new events
  were found, or "No changes to commit." if nothing new happened
  (in which case there's nothing new for the site to show anyway).
- **"Prepare Vercel deploy config"** — copies `middleware.js`/`package.json`
  into the freshly generated `site/dist/`. Should be near-instant; failure
  here means those two files are missing or renamed in `surfaces/site/` on
  `main` — check `git log -- surfaces/site/middleware.js`.
- **"Install Vercel CLI"** — `npm install -g vercel@latest`. Failure here is
  almost always a transient npm registry issue — just re-run the job.
- **"Deploy site to Vercel"** — the actual deploy. Failure modes to check:
  - `Error: No existing credentials found` → `VERCEL_TOKEN` secret is
    missing/expired.
  - `Project not found` → `VERCEL_ORG_ID`/`VERCEL_PROJECT_ID` don't match
    an actual project the token has access to — re-run `vercel link` from
    `surfaces/site/dist` locally and recheck `.vercel/project.json` against
    what's in the GitHub secrets.
  - Success prints the deployment URL directly in the log output.

## Step 4 — verify the live site

1. Open the deployment URL from the last step's log.
2. Your browser should immediately show a native Basic Auth prompt (not a
   custom login page — that's expected, it's `WWW-Authenticate: Basic`).
3. Enter any username and the `SITE_PASSWORD` you set in Vercel.
4. Confirm you land on the real feed page (405+ scored events, summary
   stats at the top) — same content you'd get running
   `python -m surfaces.site` locally, just password-gated and reachable
   over the internet instead of localhost-only.
5. Click through **Convergence** and **Competitors** in the nav to confirm
   those pages also load and are also gated (Basic Auth should cover the
   whole domain, not just the homepage — the `matcher` in
   `surfaces/site/middleware.js` is `/((?!favicon.ico).*)`, i.e. everything).
6. Try a wrong password once to confirm the 401 challenge actually rejects
   bad credentials, not just prompts cosmetically.

## If something's wrong

- Wrong/no password prompt at all → middleware isn't deployed; check
  "Prepare Vercel deploy config" actually ran and the files landed in
  `site/dist/` before `vercel deploy` (check the Vercel deployment's file
  list in its dashboard "Source" tab).
- Prompt appears but the right password doesn't work → `SITE_PASSWORD` env
  var typo, or it's set on the wrong Vercel environment (must be
  **Production**, since `vercel deploy --prod` deploys to that environment).
- Site loads but content looks stale → check which run's data actually got
  deployed; the deploy step runs after the `data` branch commit, using
  whatever `python -m surfaces.site` just generated in that same job run.
