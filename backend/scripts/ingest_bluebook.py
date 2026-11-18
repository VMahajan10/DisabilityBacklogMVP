"""Load the saved Blue Book 1.00 page and CAL list into the vector store. Usage: make ingest"""
from app.db import SessionLocal, init_db
from app.llm.registry import get_provider
from app.services.reference_data import ingest_bluebook, ingest_cal

if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    p = get_provider()
    print(f"Blue Book 1.00: {ingest_bluebook(db, p)} chunks embedded with {p.embedding_model}")
    print(f"CAL conditions: {ingest_cal(db, p)} conditions embedded")
