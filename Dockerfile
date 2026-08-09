# syntax=docker/dockerfile:1.7
#
# Investor Intelligence — self-contained image.
#
# The vector store is NOT copied from the host. It is built during the image
# build by running the three PDFs in data/raw_pdfs/ through the full pipeline:
# convert -> identify -> chunk -> embed -> extract KPIs. That takes ~25 minutes
# and spends API credit, but it happens once. The alternative — building at
# container start — would repeat all of it on every restart, and free hosts
# restart whenever they wake from sleep.
#
# Build (BuildKit required, for --secret):
#   docker build --secret id=env,src=.env -t investor-intelligence .
#
# Run:
#   docker run -p 7860:7860 --env-file .env investor-intelligence

FROM python:3.14-slim

# 1. Dependencies first, on their own layer.
#    requirements.txt changes rarely; app code changes constantly. Copying it
#    alone means editing app.js does not trigger a reinstall.
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Application code and the source PDFs.
COPY . .

# 3. Build the vector store and the KPI cache.
#
#    --mount=type=secret exposes .env to THIS STEP ONLY, as a file at
#    /run/secrets/env. It is not written to any layer, so the finished image
#    contains no keys. COPY .env would have baked them in permanently.
#
#    --mount=type=cache keeps data/uploads and data/kpi between builds, so a
#    build that dies partway (a dropped connection, an API timeout) can be
#    retried and will skip the filings that already completed — the same
#    fingerprint cache that works locally.
RUN --mount=type=secret,id=env,target=/run/secrets/env \
    --mount=type=cache,target=/srv/data/uploads \
    --mount=type=cache,target=/srv/data/kpi \
    set -a && . /run/secrets/env && set +a && \
    python -m app.pipeline && \
    cp -r /srv/data/kpi /srv/data/kpi_baked

# The KPI files were written to a cache mount, which does not persist into the
# image. Move the baked copy back into place.
RUN rm -rf /srv/data/kpi && mv /srv/data/kpi_baked /srv/data/kpi

# 4. Runtime.
#    7860 is the port HuggingFace Spaces expects.
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]