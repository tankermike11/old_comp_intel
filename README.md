# data branch

This branch holds the evolving, generated state of the One Lucky Dog CI
system — **not source code**. It's updated by `.github/workflows/monthly.yml`
on the `main` branch, which:

1. checks out this branch's `db/old_ci.sqlite3` into the pipeline's working
   directory (so history persists across each ephemeral CI run),
2. runs the monthly collection + analysis pass against it,
3. regenerates `brief/brief.md`, `deck/deck.pptx`, and `site/dist/`,
4. commits the updated files straight back here.

Do not edit files on this branch by hand — the next scheduled run will
overwrite them. If you need to reset the dataset, delete `db/old_ci.sqlite3`
here; the workflow re-initializes an empty, freshly-seeded store when the
file is missing.
