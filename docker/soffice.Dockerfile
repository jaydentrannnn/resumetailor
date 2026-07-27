# LibreOffice headless, with the resume's own fonts.
#
# Two jobs: it is the measurement engine baked into the application image, and on its own
# it is the Phase 0 spike that answers whether LibreOffice's page/line counts can stand in
# for Word's (see scripts/compare_pdf_backends.py).
#
# Fonts are the whole fidelity story. The fit loop decides where text wraps, so the
# container must use the *same font files* the baseline PDFs were rendered with, not a
# metric-compatible substitute. docker/fonts/ vendors them for exactly that reason.
#
#   docker build -f docker/soffice.Dockerfile -t resumetailor-soffice docker
#   docker run --rm -v "${PWD}/output:/work" resumetailor-soffice \
#       bash -c "soffice --headless --convert-to pdf --outdir /work/_lo /work/*.docx"

FROM debian:bookworm-slim

# libreoffice-writer alone, not the full suite: it is the only component that opens .docx,
# and skipping Calc/Impress/Base saves roughly half the image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-liberation \
        fonts-dejavu-core \
        fontconfig \
    && rm -rf /var/lib/apt/lists/*

COPY fonts/ /usr/local/share/fonts/resumetailor/
RUN fc-cache -f -v > /dev/null

# LibreOffice refuses to start without a writable profile directory, and the default
# location is the (root-owned, possibly read-only) home dir. Callers that run several
# conversions concurrently should additionally pass a per-job
# -env:UserInstallation=file:///tmp/lo_<id> to dodge the single-instance profile lock.
ENV HOME=/tmp

WORKDIR /work
