# ResumeTailor — single image: React SPA + FastAPI + LibreOffice measurement.
#
# Multi-stage: Node builds the SPA, then python:3.13-slim installs LibreOffice,
# the resume's fonts, and the package. Expect ~1 GB; LibreOffice dominates.
#
#   docker compose up --build

# --------------------------------------------------------------------------------------
# Stage 1 — SPA
# --------------------------------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --------------------------------------------------------------------------------------
# Stage 2 — runtime
# --------------------------------------------------------------------------------------
FROM python:3.13-slim-bookworm

# libreoffice-writer alone: it is the only component that opens .docx.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-liberation \
        fonts-dejavu-core \
        fontconfig \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Same font files Word used for the baseline PDFs — glyph advances must match or
# CHARS_PER_LINE becomes meaningless. Spectral was missing on the host and is installed
# here for real; headings are short, so that does not affect wrapping.
COPY docker/fonts/ /usr/local/share/fonts/resumetailor/
RUN fc-cache -f > /dev/null

WORKDIR /app

COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -e .

COPY --from=frontend /frontend/dist ./frontend/dist
COPY scripts ./scripts
COPY tailor.py ./

# data/ and templates/ are bind-mounted at runtime (gitignored, hold PII / the user's
# own resume). Create the mount points so a misconfigured compose fails clearly.
RUN mkdir -p /app/data /app/templates /app/output /app/output/cache /app/output/jobs

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    RESUME_TAILOR_PDF_BACKEND=soffice \
    RESUME_TAILOR_CACHE_DIR=/app/output/cache \
    RESUME_TAILOR_DATA_DIR=/app/data \
    RESUME_TAILOR_TEMPLATES_DIR=/app/templates \
    RESUME_TAILOR_OUTPUT_DIR=/app/output \
    HOME=/tmp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/config || exit 1

CMD ["uvicorn", "resume_tailor.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
