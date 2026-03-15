# ai-movie-suggester

A self-hosted AI companion for [Jellyfin](https://jellyfin.org/) that provides conversational movie recommendations using your actual library.

Ask it things like *"something spooky from the 80s"* or *"a comedy like Galaxy Quest"* and get recommendations from movies you actually own — then play them directly on your TV.

## Features

- **Conversational discovery** — chat naturally about what you're in the mood for
- **Your library only** — recommendations come from your Jellyfin collection, not the entire internet
- **Privacy-first** — all AI inference runs locally via [Ollama](https://ollama.ai/). No data leaves your network by default
- **Multi-user** — each user sees recommendations scoped to their Jellyfin permissions
- **Play on TV** — trigger playback on any active Jellyfin device from the recommendation screen
- **Optional TMDb enrichment** — opt-in metadata enrichment for better recommendations (see [Privacy](#privacy))

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- A running [Jellyfin](https://jellyfin.org/) server on your network
- [Ollama](https://ollama.ai/) — either an existing instance or use the bundled sidecar
- *(Optional)* [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) for GPU acceleration

### Verify GPU support (optional)

```bash
docker info | grep -i nvidia
```

If this returns nothing and you want GPU acceleration, install nvidia-container-toolkit first. Without it, Ollama falls back to CPU (slower but functional).

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/PCritchfield/ai-movie-suggester.git
cd ai-movie-suggester

# 2. Configure
cp .env.example .env
# Edit .env — fill in JELLYFIN_URL and generate a SESSION_SECRET:
#   openssl rand -hex 32

# 3. Pull Ollama models (if using bundled sidecar)
docker compose -f docker-compose.yml -f docker-compose.ollama.yml up -d ollama
docker exec -it ai-movie-suggester-ollama-1 ollama pull llama3.1:8b
docker exec -it ai-movie-suggester-ollama-1 ollama pull nomic-embed-text

# 4. Start everything
# With bundled Ollama (+ GPU):
docker compose -f docker-compose.yml -f docker-compose.ollama.yml up -d

# OR if you already run Ollama (set OLLAMA_HOST in .env):
docker compose up -d

# 5. Check health
docker compose logs -f
# Look for:
#   [startup] Jellyfin at http://... ... OK
#   [startup] Ollama at http://... ... OK

# 6. Open in browser
# http://localhost:3000
```

## Reverse Proxy (Caddy)

If you run Caddy for SSL/external access, add to your Caddyfile:

```
movies.yourdomain.duckdns.org {
    reverse_proxy localhost:3000
}
```

## Privacy

**By default, no data leaves your network.** All AI inference (chat and embeddings) runs locally on your hardware via Ollama.

**Optional: TMDb enrichment.** When `TMDB_ENABLED=true`, the app queries the [TMDb API](https://www.themoviedb.org/) to enrich movie metadata (descriptions, keywords, cast). This improves recommendation quality but sends the following to TMDb's servers:

- Movie title search queries
- Your server's public IP address
- Your TMDb API key

No watch history, user credentials, or personal data are sent. TMDb enrichment can be disabled at any time by setting `TMDB_ENABLED=false` — the app works fully with Jellyfin's own metadata.

## Development

```bash
# Full stack with hot reload
make dev

# Frontend only (no Ollama needed)
make dev-ui

# Run tests
make test

# Lint
make lint
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design and data flow diagrams.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python (FastAPI) |
| Frontend | Next.js (App Router) |
| Vector DB | SQLite-vec |
| LLM | Ollama (llama3.1:8b) |
| Embeddings | Ollama (nomic-embed-text) |
| Orchestration | Docker Compose |

## License

TBD
