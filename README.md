# wpSBOOT server

Web server for building **Super-MSAs**: the same sequences are aligned by several
aligners (MAFFT, MUSCLE, ClustalW, T-Coffee) and the alignments are concatenated with
the lab's `concatenate.pl`, ready for weighted partial super bootstrap (wpSBOOT).

> Chang J-M, Floden EW, Herrero J, Gascuel O, Di Tommaso P, Notredame C.
> Incorporating alignment uncertainty into Felsenstein's phylogenetic bootstrap to improve
> its reliability. *Bioinformatics* 37(11):1506–1514, 2021.
> [doi:10.1093/bioinformatics/btz082](https://doi.org/10.1093/bioinformatics/btz082)

The original 2019 Flask server is kept under the `v1-legacy` git tag.

## Architecture

```
browser ──HTTPS──> Caddy ──> web (FastAPI) ──┐
                                             ├── PostgreSQL (data + job queue)
                   worker × N ───────────────┘
                     └─ mafft, muscle, clustalw, t_coffee, perl + BioPerl
                   shared volume: /data/jobs/<job id>/
```

- **web** serves the one-page site, the result pages, the JSON API (`/api/v1`,
  docs at `/api/docs`) and the admin panel (`/admin`).
- **worker** claims queued jobs (`FOR UPDATE SKIP LOCKED`), runs the selected aligners in
  parallel with a deadline, then runs `tools/concatenate.pl` unmodified. Heartbeats let a
  crashed worker's job be picked up again; finished jobs expire after `RETENTION_DAYS`.
- **migrate** applies Alembic migrations before web and workers start.
- **backup** writes a daily `pg_dump` (job files are temporary and not backed up).

| Tool | Version (bioconda) |
|---|---|
| MAFFT | 7.525 |
| MUSCLE | 3.8.1551 |
| ClustalW | 2.1 |
| T-Coffee | 11.00.8cbe486 |
| BioPerl | 1.7.8 |

Aligner arguments are the ones used by the original `wpSBOOT.sh`. The versions used for
each job are recorded and shown on its result page.

## Deploying

See **[docs/deploy.md](docs/deploy.md)** (Traditional Chinese). Project status and open decisions: [docs/PROGRESS.md](docs/PROGRESS.md). In short:

```sh
cp .env.example .env        # set DOMAIN, SECRET_KEY, POSTGRES_PASSWORD, ADMIN_PASSWORD, SMTP_*
docker compose up -d --build
```

## Developing

Requirements: Docker with Compose v2, and [uv](https://docs.astral.sh/uv/) for running
checks outside containers.

```sh
cp .env.example .env    # set SECRET_KEY, POSTGRES_PASSWORD, PUBLIC_BASE_URL=http://localhost:8000
                        # and uncomment COMPOSE_FILE=compose.yaml:compose.dev.yaml
docker compose up -d --build            # hot reload on :8000, Mailpit on :8025
```

- Site: http://localhost:8000, admin: http://localhost:8000/admin (admin / admin)
- Mail sent by the worker: http://localhost:8025
- Postgres: `127.0.0.1:55432`

Tests and checks:

```sh
# Everything, including the real aligners, inside the worker image:
docker compose --profile test run --rm --build test

# Fast loop on the host (tests marked `db` need DATABASE_URL, `tools` need the aligners):
cd app
uv sync
DATABASE_URL=postgresql+psycopg://wpsboot:<password>@127.0.0.1:55432/wpsboot_test uv run pytest
uv run ruff check src tests migrations && uv run ruff format --check src tests migrations
SECRET_KEY=dev uv run mypy
```

Database changes: edit `app/src/wpsboot/models.py`, then

```sh
cd app
DATABASE_URL=postgresql+psycopg://wpsboot:<password>@127.0.0.1:55432/wpsboot \
  uv run alembic revision --autogenerate -m "describe the change"
```

Review the generated file in `app/migrations/versions/` before committing.

### Layout

```
app/src/wpsboot/
  api.py          JSON API
  web.py          HTML pages
  admin.py        admin panel
  services.py     job lifecycle shared by API, admin and worker
  pipeline.py     runs aligners and concatenate.pl (no database)
  worker.py       queue consumer
  fasta.py        input validation
  models.py       SQLAlchemy models
app/migrations/   Alembic
app/tests/        pytest (fakes/ holds stand-in aligners)
tools/            concatenate.pl from the lab, unmodified
docker/Dockerfile targets: web, worker, test
```

## Contact

Dr. Jia-Ming Chang, Department of Computer Science, National Chengchi University —
chang.jiaming@gmail.com — http://www.changlabtw.com/
