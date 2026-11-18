from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.db import init_db
from app.routers import analysis, audit, claims, documents, listings, metrics

app = FastAPI(title="DDS Examiner Copilot (prototype)", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

init_db()
for r in (claims, documents, analysis, audit, listings, metrics):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"ok": True, "provider": config.LLM_PROVIDER, "model": config.OPENAI_MODEL}


@app.get("/api/me")
def me():
    return config.DEMO_EXAMINER
