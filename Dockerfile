# syntax=docker/dockerfile:1.7
#
# Investor Intelligence — self-contained image.
#
# The vector store is not copied from the host. It is built during the image
# build by running the PDFs in data/raw_pdfs/ through the full pipeline:
# convert -> identify -> chunk -> embed -> extract KPIs. That takes ~25 minutes
# and spends API credit, but it happens once, and the resulting image needs no
# database, no volume and no external state.
#
# Building at container start instead would repeat all of it on every restart,
# and would require a persistent volume, which is the part of most free hosting
# tiers that costs money.
#
# Build:
#   docker build \
#     --secret id=GOOGLE_API_KEY,env=GOOGLE_API_KEY \
#     --secret id=OPENROUTER_API_KEY,env=OPENROUTER_API_KEY \
#     --secret id=DATALAB_API_KEY,env=DATALAB_API_KEY \
#     -t investor-intelligence .
#
# Run:
#   docker run -p 8000:8000 --env-file .env investor-intelligence
#
# Measured: 989 MB image, 455 MB resident at idle.

# Two stages, so CI can validate everything up to the pipeline without holding
# any credentials:
#
#   docker build --target base .   dependencies + code. No secrets, no API
#                                  calls, ~2 min. Runs on every push.
#   docker build .                 the full image. Needs all three keys and
#                                  ~25 minutes. Run deliberately, not on push.
#
# The second stage inherits USER, WORKDIR and ENV from the first, so nothing is
# repeated below.
FROM python:3.14-slim AS base

# Run as a non-root user. Created before any COPY so that files are owned
# correctly on the way in: a later recursive chown would duplicate every
# affected file into a new layer and roughly double the image size.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH
WORKDIR $HOME/app

# Dependencies on their own layer. requirements.txt changes rarely and
# application code changes constantly, so copying it alone means editing
# app.js does not trigger a reinstall.
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .


FROM base AS final

# Build the vector store and the KPI cache.
#
# --mount=type=secret exposes each key to this step only, as a file under
# /run/secrets/. Nothing is written to a layer, so the finished image contains
# no credentials. COPY .env would have baked them in permanently.
#
# required=true fails the build immediately if a secret is missing, instead of
# proceeding with an empty key and failing later inside an API call.
#
# Only the three keys this application uses are passed.
RUN --mount=type=secret,id=GOOGLE_API_KEY,mode=0444,required=true \
    --mount=type=secret,id=OPENROUTER_API_KEY,mode=0444,required=true \
    --mount=type=secret,id=DATALAB_API_KEY,mode=0444,required=true \
    export GOOGLE_API_KEY=$(cat /run/secrets/GOOGLE_API_KEY) && \
    export OPENROUTER_API_KEY=$(cat /run/secrets/OPENROUTER_API_KEY) && \
    export DATALAB_API_KEY=$(cat /run/secrets/DATALAB_API_KEY) && \
    python -m app.pipeline && \
    rm -rf data/uploads

# PORT is read from the environment so the image runs unchanged on hosts that
# assign one (Cloud Run, Render, Spaces). Defaults to 8000 locally.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
