# Personal Memory

- The user calls this assistant “星期五”. Use that name when asked.

# Deployment

- Read `ops/README.md` before deploying the frontend and Python backend.
- The unified entry is `ops/deploy.sh`. `check` is read-only; `stage` builds and verifies an isolated candidate without switching live traffic; `deploy` switches production and requires the user's deployment instruction.
- Build changed code with `ops/package.sh` before publishing. Keep `release/` and its checksums consistent.
- Reuse the ignored local `deploy/config.env` / `ops/local.env`. Never commit credentials or print secret values.
- Preserve unrelated edits made by other chats. Stage only files belonging to the current task.
- Do not use the legacy Java publishing script for Python migration. Preserve production notes, skills and databases, and report actual verification results and any remaining functional gaps.
