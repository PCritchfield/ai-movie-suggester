# 01-task-04-proofs — CI Workflow + Dependabot Configuration

## Workflow Structure Validation

```
$ python3 structural_check.py  # inline validation script

  [OK] on: trigger
  [OK] PR trigger
  [OK] push trigger
  [OK] schedule trigger
  [OK] manual trigger
  [OK] service container
  [OK] pinned image
  [OK] healthcheck
  [OK] warmer step
  [OK] SHA-pinned uv
  [OK] test step
  [OK] pass-through job
  [OK] test URL env
```

## Workflow Triggers

```yaml
on:
  pull_request:
    branches: [main]
    paths: ['backend/**', '.github/workflows/integration.yml']
  push:
    branches: [main]
  schedule:
    - cron: '0 6 * * 1'   # Monday 6am UTC
  workflow_dispatch:
```

## SHA-Pinned Actions

| Action | Pin | Version |
|--------|-----|---------|
| `astral-sh/setup-uv` | `38f3f104447c67c051c4a08e39b64a148898af3a` | v4 |
| `actions/checkout` | `v4` | GitHub-org (tag OK) |
| `actions/setup-python` | `v5` | GitHub-org (tag OK) |
| `actions/cache` | `v4` | GitHub-org (tag OK) |

SHA resolved via: `gh api repos/astral-sh/setup-uv/git/ref/tags/v4` → dereference annotated tag → commit SHA.

## Service Container Configuration

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin:10.10.7
    ports: [8096:8096]
    options: >-
      --health-cmd "curl -sf http://localhost:8096/health"
      --health-interval 10s
      --health-timeout 5s
      --health-retries 10
```

## Warmer Step

Polls `GET /System/Info/Public` as secondary readiness gate (Jellyfin `/health` can return 200 before full API is ready). 120s timeout.

## Pass-Through Job

`integration-check` inspects `needs.integration.result`, matching the `backend-check` / `frontend-check` pattern in `ci.yml`. NOT registered as a required check (advisory-only per spec).

## Dependabot Configuration

```
$ cat .github/dependabot.yml

  [OK] version 2
  [OK] docker-compose ecosystem
  [OK] weekly schedule
```

Monitors all images in `docker-compose.test.yml` (currently only Jellyfin). Comment notes additional ecosystems can be added in future PRs.

## Live CI Verification

Live CI verification (push + PR trigger + `gh workflow run`) will be completed after this branch is pushed. Structural validation confirms all spec requirements are met in the YAML.

## Verification

- [x] Workflow has correct triggers (PR paths, push main, weekly, manual)
- [x] Jellyfin service container with healthcheck
- [x] Warmer step for API readiness
- [x] SHA-pinned non-GitHub-org actions
- [x] Test step with `JELLYFIN_TEST_URL=http://localhost:8096`
- [x] Pass-through `integration-check` job
- [x] No `continue-on-error: true` on integration job
- [x] Dependabot docker-compose ecosystem configured
