FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first for layer caching.
COPY pyproject.toml ./
COPY src ./src
RUN pip install -e ".[gemini]"

COPY web ./web
COPY data/raw ./data/raw
COPY data/eval.jsonl ./data/eval.jsonl

# The index is built at image build time from the committed sample, so a container
# starts serving immediately and every image carries a known-good index.
RUN takam-ingest build

RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "takam_search.api:app", "--host", "0.0.0.0", "--port", "8000"]
