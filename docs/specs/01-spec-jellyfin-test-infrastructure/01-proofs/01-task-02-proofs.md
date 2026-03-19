# 01-task-02-proofs — Jellyfin Docker Fixture + Makefile Targets

## CLI Output: `make jellyfin-up` starts healthy Jellyfin

```
$ make jellyfin-up

docker compose -p ai-movie-suggester-test -f docker-compose.test.yml up -d jellyfin
 Container ai-movie-suggester-test-jellyfin-1  Created
 Container ai-movie-suggester-test-jellyfin-1  Started
Waiting for Jellyfin to become healthy...
Jellyfin available at http://localhost:8096
```

## CLI Output: `docker compose ps` shows `(healthy)`

```
$ docker compose -p ai-movie-suggester-test -f docker-compose.test.yml ps

NAME                                 IMAGE                       STATUS                    PORTS
ai-movie-suggester-test-jellyfin-1   jellyfin/jellyfin:10.10.7   Up 20 seconds (healthy)   127.0.0.1:8096->8096/tcp
```

## CLI Output: `curl http://localhost:8096/health`

```
$ curl -sf http://localhost:8096/health
Healthy
```

## CLI Output: `make jellyfin-down` removes container and volumes

```
$ make jellyfin-down

docker compose -p ai-movie-suggester-test -f docker-compose.test.yml down -v
 Container ai-movie-suggester-test-jellyfin-1  Stopped
 Container ai-movie-suggester-test-jellyfin-1  Removed
 Volume ai-movie-suggester-test_jellyfin-test-config  Removed
 Volume ai-movie-suggester-test_jellyfin-test-cache  Removed
 Network ai-movie-suggester-test_default  Removed
```

## CLI Output: `make test-integration-full` completes start-test-teardown cycle

```
$ make test-integration-full

docker compose -p ai-movie-suggester-test -f docker-compose.test.yml up -d jellyfin
 Container ai-movie-suggester-test-jellyfin-1  Created
 Container ai-movie-suggester-test-jellyfin-1  Started
Waiting for Jellyfin to become healthy...
Jellyfin available at http://localhost:8096
cd backend && JELLYFIN_TEST_URL=http://localhost:8096 uv run pytest -m integration -v
tests/integration/test_smoke.py::test_placeholder PASSED                 [100%]
======================= 1 passed, 2 deselected in 0.01s ========================
docker compose -p ai-movie-suggester-test -f docker-compose.test.yml down -v
 Container ai-movie-suggester-test-jellyfin-1  Removed
 Volume ai-movie-suggester-test_jellyfin-test-config  Removed
 Volume ai-movie-suggester-test_jellyfin-test-cache  Removed
```

## CLI Output: Unconditional teardown with failing test

```
$ make test-integration-full  # with assert False in placeholder test

tests/integration/test_smoke.py::test_placeholder FAILED                 [100%]
FAILED tests/integration/test_smoke.py::test_placeholder - AssertionError: Deliberate failure
======================= 1 failed, 2 deselected in 0.03s ========================
make[1]: *** [test-integration] Error 1
docker compose -p ai-movie-suggester-test -f docker-compose.test.yml down -v
 Container ai-movie-suggester-test-jellyfin-1  Removed
 Volume ai-movie-suggester-test_jellyfin-test-cache  Removed
 Volume ai-movie-suggester-test_jellyfin-test-config  Removed

$ docker ps --filter "name=ai-movie-suggester-test"
CONTAINER ID   IMAGE     COMMAND   CREATED   STATUS    PORTS     NAMES
```

**Result:** `jellyfin-down` ran unconditionally despite test failure. No orphaned containers.

## Deviations from Spec

1. **`test-integration` runs on host, not in dev container.** `docker compose run` does not support `--add-host`, and the base `docker-compose.yml` requires a `.env` file. Running via `cd backend && uv run pytest` on the host matches CI behavior, avoids both issues, and is simpler. `JELLYFIN_TEST_URL=http://localhost:8096` since Jellyfin is on the host.

2. **`extra_hosts` added to `docker-compose.dev.yml`.** Added `host.docker.internal:host-gateway` to the backend service for future use by any target that does run inside the container. Harmless on Mac, needed on Linux.

## Verification

- [x] `make jellyfin-up` starts healthy container
- [x] `curl /health` returns `Healthy`
- [x] `make jellyfin-down` removes container and volumes
- [x] `make test-integration-full` completes full cycle
- [x] Unconditional teardown works with failing tests
- [x] No orphaned containers after failure
- [x] `ruff check` and `ruff format --check` pass
