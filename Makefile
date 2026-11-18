PY := backend/.venv/bin/python

.PHONY: setup synth synth-large dev test eval compare-map ingest seed reset

setup:            ## install backend + frontend deps, generate synthetic PDFs
	cd backend && uv sync
	cd frontend && npm install
	$(MAKE) synth
	@test -f .env || (cp .env.example .env && echo "Created .env - add your OPENAI_API_KEY")

synth:            ## regenerate synthetic claim PDFs
	$(PY) data/synthetic/generate.py

synth-large:      ## generate the ~150 / ~500 / ~1,500-page cases (cached LLM notes)
	$(PY) data/synthetic/large/generate_large.py

compare-map:      ## one-time: map summaries with fast vs main model on the 150-page case
	cd backend && .venv/bin/python -m eval.compare_map_models

dev:              ## run backend + frontend
	./scripts/dev.sh

test:             ## run pytest
	cd backend && .venv/bin/pytest -q

ingest:           ## load Blue Book 1.00 text into the listing vector store
	cd backend && .venv/bin/python -m scripts.ingest_bluebook

seed:             ## seed demo metrics data
	cd backend && .venv/bin/python -m scripts.seed_demo

eval:             ## run full pipeline on all synthetic cases (calls the LLM)
	cd backend && CASES=$(CASES) .venv/bin/python -m eval.run_eval

reset:            ## delete local DB and uploads
	rm -rf backend/storage
