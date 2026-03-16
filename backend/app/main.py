from fastapi import FastAPI

app = FastAPI(title="ai-movie-suggester")


@app.get("/health")
async def health():
    return {"status": "ok"}
