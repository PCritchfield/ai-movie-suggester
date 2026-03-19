# 01 Questions Round 1 - Jellyfin Test Infrastructure

Please answer each question below (select one or more options, or add your own notes). Feel free to add additional context under any question.

## 1. CI Workflow Strategy

Moist recommended a separate `integration.yml` workflow (keeps fast checks fast, different trigger policy). Magrat suggested a new job in existing `ci.yml`. Where should integration tests live in CI?

- [x] (A) Separate workflow (`integration.yml`) — independent triggers, doesn't slow PR feedback
- [ ] (B) New job in existing `ci.yml` — single file to maintain, same trigger policy
- [ ] (C) Other (describe)

## 2. Integration Test CI Status

Should integration tests be a required branch protection check from the start, or advisory-only until the fixture proves reliable?

- [x] (A) Advisory-only initially (`continue-on-error: true`) — earn trust first, promote to required later
- [ ] (B) Required from the start — if integration tests fail, the PR should not merge
- [ ] (C) Other (describe)

## 3. CI Trigger Policy

When should integration tests run in CI?

- [x] (A) On every PR that touches `backend/**` + always on merge to main + weekly scheduled + manual dispatch
- [ ] (B) On every PR that touches `backend/**` + always on merge to main + manual dispatch (no scheduled)
- [ ] (C) Only on merge to main + manual dispatch (keep PRs fast, catch issues after merge)
- [ ] (D) Other (describe)

## 4. Test Runner Environment

Should integration tests run directly on the CI runner (pytest on host, Jellyfin in service container) or inside the dev Docker container (like `make test` does)?

- [ ] (A) Directly on CI runner — simpler networking (localhost:8096), matches how devs run locally outside Docker
- [x] (B) Inside dev container — consistent with existing `make test` pattern, but needs `host.docker.internal` networking
- [ ] (C) Other (describe)

## 5. Smoke Test Scope

What should the initial integration smoke tests verify? (Select all that apply)

- [x] (A) Jellyfin is reachable and healthy
- [x] (B) Can complete first-run setup wizard programmatically
- [ ] (C) Can create test users via API
- [ ] (D) Can authenticate as test user (get AccessToken)
- [ ] (E) Can fetch library items as authenticated user (empty list is fine)
- [ ] (F) Can revoke a token / logout
- [ ] (G) Other (describe)

## 6. Local Developer Experience

How should developers run integration tests locally?

- [ ] (A) Two-step: `make jellyfin-up` then `make test-integration` (explicit control)
- [ ] (B) One-step: `make test-integration-full` handles start, test, teardown
- [x] (C) Both (A) and (B) as separate targets
- [ ] (D) Other (describe)

## 7. Jellyfin Version Strategy

Should we pin to a specific Jellyfin version or track latest?

- [ ] (A) Pin to specific version (`jellyfin/jellyfin:10.10.7`) — reproducible, update manually
- [ ] (B) Track latest (`jellyfin/jellyfin:latest`) — always test against current
- [x] (C) Pin + add Dependabot/Renovate config for automated version bump PRs
- [ ] (D) Other (describe)
