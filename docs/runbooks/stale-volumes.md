# Stale Named Volumes

## Problem

The dev environment (`docker-compose.dev.yml`) uses named volumes to persist installed dependencies across container restarts:

| Volume | Mount | Contents |
|--------|-------|----------|
| `backend-venv` | `/app/.venv` | Python virtualenv (uv) |
| `frontend-node-modules` | `/app/node_modules` | npm packages |
| `frontend-next-cache` | `/app/.next` | Next.js build cache |

When lockfiles change (`uv.lock` or `package-lock.json`) -- for example after pulling new commits -- the named volumes retain stale dependencies from the previous build. The container starts with outdated packages that no longer match the lockfile.

## Symptoms

- `ModuleNotFoundError` or `ImportError` in the backend
- `MODULE_NOT_FOUND` errors in the frontend
- Version mismatch warnings or runtime errors after pulling changes
- Tests pass in CI but fail locally

## Fix

### Nuclear option (removes all dev volumes)

```bash
docker compose down -v && docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

### Targeted removal

Remove only the affected volume(s):

```bash
# Stop containers first
docker compose down

# Remove specific volumes
docker volume rm ai-movie-suggester_backend-venv
docker volume rm ai-movie-suggester_frontend-node-modules
docker volume rm ai-movie-suggester_frontend-next-cache

# Rebuild
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

> **Note:** The volume prefix (`ai-movie-suggester_`) is derived from the project directory name. If your clone lives in a differently-named directory, the prefix will differ. Use `docker volume ls | grep venv` to find the exact name.
