# CLAUDE.md — Smart CMM Quality Alert and Action Tracking System

Read docs/BUILD_SPEC.md completely before writing code. It is the source of truth.

## How to work
- Build one phase at a time, in the order of Section 22. Do not start the next phase until the
  current phase's acceptance criteria pass and `make test` and `make lint` pass.
- Work in commit units C01–C37 (Section 23.3). At the end of each unit, STOP and print:
  1) the commit ID and exact commit message from Section 23.3,
  2) the list of files created or changed,
  3) how you verified it (tests run and their result).
  Then wait for the user to say "next".
- Use exactly the repository structure in Section 21 so the user's git add paths work.

## Git
- NEVER run git commands that change state: add, commit, push, merge, rebase, tag, checkout,
  reset, stash, branch. The user runs all git commands manually.
- Read-only `git status` and `git diff --stat` are allowed.

## Engineering rules
- The core loop (ingest, classify, NC, alert, escalate, corrective action, KPI) must be fully
  deterministic and must never call an AI/LLM. AI code lives only in backend/app/ai/ and runs
  only when AI_ENABLED=true.
- Use Decimal for all tolerance comparisons (Section 9). Limits are inclusive.
- Report + measurements + NC + alerts + outbox are written in one transaction.
- Every state change writes an audit_log entry. audit_log is append-only.
- Server-side permission checks on every write endpoint.
- Write tests with each engine; golden cases in Sections 9.3, 12.4 and 13 must pass exactly.
- No secrets in code. Use .env (gitignored) and document keys in .env.example.
- Label all generated data as demo/synthetic. Never invent real plant data or numbers.
- Pin dependency versions in lockfiles.

## When unsure
- If a domain rule is ambiguous (tolerances, KPI definitions, state transitions), ask the user
  instead of guessing. Do not change a definition in BUILD_SPEC.md without asking.
