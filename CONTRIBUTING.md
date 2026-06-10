# Contributing

Thanks for your interest! A few things up front so we don't waste each other's time.

## What this project is

`ai-movie-suggester` is a **personal learning project** — a self-hosted, privacy-first RAG companion for Jellyfin. It's developed in the open, but it is **not** a community-governed product. The roadmap, scope, and design direction are the maintainer's call.

Outside contributions are welcome, but a clean, well-scoped PR is **not** a guarantee of merge: if a change doesn't fit where the project is headed, it may be declined with thanks. Please don't take a polite "no" personally.

## Before you open a pull request

1. **Open or claim an issue first.** Comment on the issue you'd like to take so we don't duplicate effort — and so we can confirm it's something the project actually wants *before* you spend time on it. Unsolicited PRs with no associated issue, or that don't match an agreed direction, may be closed without review.
2. **Branch from the latest `main`.** This repo moves quickly and work is often in flight. A branch cut from a stale `main` tends to miss the real call sites or collide with unmerged work. Rebase before you open the PR, and keep it current (CI requires the branch to be up to date).
3. **Finish the whole task.** A change should resolve its issue *completely* — every affected call site, not just the convenient one — and arrive with tests.

## Working on a change

- **Tests are required.** This project follows TDD: a failing test first, then the code that makes it pass. Match the patterns in the existing suite. Run `make test` and `make lint` before you push.
- **Match the codebase.** Python: `async/await` for I/O, full type hints, `ruff`. TypeScript: strict, no `any`. The full standards and the firm "Things to Avoid" list live in [`CLAUDE.md`](CLAUDE.md); the system design is in [`ARCHITECTURE.md`](ARCHITECTURE.md).
- **Conventional commits** (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, …).
- **No secrets, no PII, no plaintext tokens.** These are hard constraints, not preferences — see "Things to Avoid" in `CLAUDE.md`.

## A note on AI-assisted contributions

AI tools are welcome here — this project is itself partly an experiment in AI-assisted development. But two expectations:

- **Understand and own what you submit.** If you can't explain why a change is correct, or how it affects the rest of the system, don't open the PR. "The model wrote it" is not a substitute for understanding it.
- **Don't farm contributions.** Low-effort changes that exist mainly to land a commit or pad a contribution graph create maintainer work without adding value. They'll be recognized as such and closed.

One PR you understand deeply is worth more than ten you don't.

## How review works

Changes go through a Spec-Driven Development workflow and a set of automated reviewers (CI + Copilot). **PRs from forks require maintainer approval before CI will run** — this is a deliberate security gate, so expect a short wait. This is a side project, not a job; patience appreciated.

Thanks for reading this far. 🎬
