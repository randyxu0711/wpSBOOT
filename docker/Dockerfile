# syntax=docker/dockerfile:1.7
#
# Targets:
#   web     FastAPI app (no bioinformatics tools)
#   worker  web + aligners + BioPerl
#   test    worker + dev dependencies and tests

# --- bioinformatics toolchain (conda env at a fixed prefix so it can be copied) ---
# t-coffee pulls in BLAST and entrez-direct for its homology-search modes; the pipeline only
# runs the default proba_pair mode, so those files are deleted again (~680 MB).
FROM mambaorg/micromamba:1.5.10-bookworm-slim AS tools
USER root
# The package cache mount lets a retry resume downloads (~300 MB from conda channels).
RUN --mount=type=cache,target=/opt/conda/pkgs \
    for attempt in 1 2 3; do \
      micromamba create -y -p /opt/tools -c conda-forge -c bioconda \
        mafft=7.525 \
        muscle=3.8.1551 \
        clustalw=2.1 \
        t-coffee=11.00.8cbe486 \
        perl-bioperl=1.7.8 \
      && break; \
      [ "$attempt" = 3 ] && exit 1; rm -rf /opt/tools; sleep 10; \
    done \
    && micromamba list -p /opt/tools --json > /opt/tools/conda-packages.json \
    && find /opt/tools -name '*.a' -delete \
    && rm -rf /opt/tools/docs /opt/tools/man /opt/tools/include \
    && for p in 'blast-[0-9]*' 'blast-legacy-*' 'entrez-direct-*'; do \
         grep -ho '"\(bin\|lib\|libexec\|share\)/[^"]*"' /opt/tools/conda-meta/$p.json | tr -d '"'; \
       done | sort -u > /tmp/unused.txt \
    && (cd /opt/tools && xargs -a /tmp/unused.txt rm -f) \
    && rm /tmp/unused.txt \
    && rm -f /opt/tools/libexec/mafft/dash_client \
    && find /opt/tools -type d -empty -delete

# --- Python app base ---
FROM python:3.12-slim-bookworm AS web
# The base image tag lags behind Debian security updates, so refresh its packages on every build.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
WORKDIR /opt/wpsboot/app
COPY app/pyproject.toml app/uv.lock ./
RUN --mount=type=bind,from=ghcr.io/astral-sh/uv:0.11.16,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-install-project
COPY app/ ./
RUN --mount=type=bind,from=ghcr.io/astral-sh/uv:0.11.16,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /data/jobs \
    && chown app:app /data/jobs
USER app
EXPOSE 8000
CMD ["uvicorn", "--factory", "wpsboot.main:create_app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]

# --- worker: app + toolchain ---
FROM web AS worker
USER root
COPY --from=tools /opt/tools /opt/tools
COPY tools/concatenate.pl /opt/wpsboot/tools/concatenate.pl
ENV PATH=/opt/venv/bin:/opt/tools/bin:$PATH \
    TOOLS_PACKAGES_FILE=/opt/tools/conda-packages.json
USER app
CMD ["wpsboot-worker"]

# --- test: worker + dev dependencies ---
FROM worker AS test
USER root
RUN --mount=type=bind,from=ghcr.io/astral-sh/uv:0.11.16,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen \
    && chown -R app:app /opt/wpsboot/app
USER app
CMD ["pytest"]
