# wpSBOOT server

Web server for building **Super-MSAs** for Weighted Partial Super Bootstrap (wpSBOOT).

## About wpSBOOT

> We demonstrate that incorporating MSA induced uncertainty into bootstrap sampling can
> significantly increase correlation between clade correctness and its corresponding bootstrap
> value. Our procedure involves concatenating several alternative multiple sequence alignments of
> the same sequences, produced using different commonly used aligners. We then draw bootstrap
> replicates while favoring columns of the more unique aligner among the concatenated aligners.
> We named this concatenation and bootstrapping method, Weighted Partial Super Bootstrap
> (wpSBOOT).

This server performs the first half of that procedure: the submitted sequences are aligned by
several aligners (MAFFT, MUSCLE, ClustalW, T-Coffee) and the alignments are concatenated into a
Super-MSA (PHYLIP) with the lab's `concatenate.pl`. Weighted bootstrap sampling is done
afterwards on the downloaded Super-MSA.

```
FASTA ──┬── MAFFT ────┐
        ├── MUSCLE ───┤
        ├── ClustalW ─┼── concatenate.pl ──> superMSA.phylip
        └── T-Coffee ─┘   (random order)
```

## Citation

> Chang J-M, Floden EW, Herrero J, Gascuel O, Di Tommaso P, Notredame C.
> Incorporating alignment uncertainty into Felsenstein's phylogenetic bootstrap to improve
> its reliability. *Bioinformatics* 37(11):1506–1514, 2021.
> [doi:10.1093/bioinformatics/btz082](https://doi.org/10.1093/bioinformatics/btz082)

```bibtex
@article{chang2021wpsboot,
  author = {Chang, Jia-Ming and Floden, Evan W and Herrero, Javier and Gascuel, Olivier and Di Tommaso, Paolo and Notredame, Cedric},
  title = {Incorporating alignment uncertainty into {Felsenstein's} phylogenetic bootstrap to improve its reliability},
  journal = {Bioinformatics},
  volume = {37},
  number = {11},
  pages = {1506--1514},
  year = {2021},
  doi = {10.1093/bioinformatics/btz082}
}
```

## Features

- Paste or upload FASTA (protein or nucleotide), choose 2–4 aligners, get the Super-MSA plus
  each individual alignment, one by one or as a zip.
- No account needed: every job gets a private result URL, and the browser remembers your recent
  jobs.
- Input is checked before anything runs, including sequence names that would collide once
  PHYLIP cuts them to 10 characters.
- The tool versions used are recorded on each result page, so results can be reproduced.
- Optional email notification when a job finishes.
- JSON API with interactive docs at `/api/docs`, and a password-protected admin panel at
  `/admin`.

## Try it locally

Requires Docker with Compose v2 on an x86_64 machine (MUSCLE 3.8 has no ARM build). The first
build downloads about 300 MB of bioinformatics packages.

```sh
git clone https://github.com/randyxu0711/wpSBOOT.git
cd wpSBOOT
cp .env.example .env
secret() { python3 -c "import secrets; print(secrets.token_urlsafe(48))"; }
sed -i \
  -e "s|^# COMPOSE_FILE=|COMPOSE_FILE=|" \
  -e "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=http://localhost:8000|" \
  -e "s|^SECRET_KEY=.*|SECRET_KEY=$(secret)|" \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(secret)|" \
  .env
docker compose up -d --build
```

| URL | |
|---|---|
| http://localhost:8000 | the site: click **Load sample sequences**, then **Build Super-MSA** |
| http://localhost:8000/admin | admin panel (admin / admin in local mode) |
| http://localhost:8000/api/docs | API documentation |
| http://localhost:8025 | Mailpit, catches the notification emails |

Stop with `docker compose down` (data is kept in Docker volumes).

## Deploying

On a Linux server with Docker, ports 80 and 443 open, and a DNS record pointing at it. Caddy
obtains the HTTPS certificate automatically.

```sh
git clone https://github.com/randyxu0711/wpSBOOT.git
cd wpSBOOT
DOMAIN=wpsboot.example.org          # <- your hostname
cp .env.example .env
chmod 600 .env
secret() { python3 -c "import secrets; print(secrets.token_urlsafe(48))"; }
sed -i \
  -e "s|^DOMAIN=.*|DOMAIN=$DOMAIN|" \
  -e "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://$DOMAIN|" \
  -e "s|^SECRET_KEY=.*|SECRET_KEY=$(secret)|" \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(secret)|" \
  -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$(secret)|" \
  .env
docker compose up -d --build

docker compose ps                   # db, web, worker: healthy; migrate: exited (0)
curl -I "https://$DOMAIN/healthz"   # HTTP 200
grep '^ADMIN_' .env                 # your /admin login
```

> [!WARNING]
> The admin panel defaults to **admin / admin**. The commands above replace the password with a
> random one; if you edit `.env` by hand instead, change `ADMIN_PASSWORD` before the server is
> reachable, or leave it empty to disable `/admin`. While the default is in use, the admin pages
> show a red warning and the web container logs one at startup.

After the first visit from another machine, run `docker compose logs web | tail` and check that
the request lines show that machine's IP address. If every request comes from a `172.x.x.x`
Docker address instead, all visitors share one rate limit.

Email, capacity, updates, backups and troubleshooting are covered in the full deployment guide
**[docs/deploy.md](docs/deploy.md)** (Traditional Chinese).

## Configuration

All settings live in `.env`; `.env.example` lists them with their defaults. The main ones:

| Variable | Default | |
|---|---|---|
| `DOMAIN`, `PUBLIC_BASE_URL` | localhost | public hostname and the base URL used in emails |
| `SECRET_KEY`, `POSTGRES_PASSWORD` | — | required random strings; don't change `POSTGRES_PASSWORD` after the first start |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | admin / admin | empty password disables `/admin` |
| `SMTP_HOST` … `MAIL_FROM` | empty | email is off (and the form field hidden) while `SMTP_HOST` is empty |
| `MAX_SEQUENCES` / `MAX_SEQUENCE_LENGTH` / `MAX_UPLOAD_BYTES` | 200 / 10,000 / 2 MB | input limits |
| `RATE_LIMIT_PER_HOUR` / `MAX_ACTIVE_JOBS_PER_IP` | 10 / 2 | per client address |
| `JOB_TIMEOUT_SECONDS` / `RETENTION_DAYS` | 1800 / 14 | time limit per job, and how long results are kept |
| `WORKER_REPLICAS` / `WORKER_CPUS` / `WORKER_MEMORY` | 2 / 2 / 4g | each worker runs one job at a time |

## API

The website uses the same API. Submit a file, poll the job, download the results:

```sh
curl -F file=@sequences.fasta -F aligners=mafft -F aligners=muscle \
     https://wpsboot.example.org/api/v1/jobs
# {"id": "3f2c…", "status": "queued", "status_url": "…", "result_url": "…", "warnings": []}

curl https://wpsboot.example.org/api/v1/jobs/3f2c…            # status, steps, file list
curl -OJ https://wpsboot.example.org/api/v1/jobs/3f2c…/archive  # zip of all results
```

Leave out `aligners` to use all four. Errors come back as `{"errors": ["…"]}` with status 422
(invalid input), 413 (too large) or 429 (rate limited).

## Architecture

```
browser ──HTTPS──> Caddy ──> web (FastAPI) ──┐
                                             ├── PostgreSQL (data + job queue)
                   worker × N ───────────────┘
                     └─ mafft, muscle, clustalw, t_coffee, perl + BioPerl
                   shared volume: /data/jobs/<job id>/
```

- **web** serves the one-page site, the result pages, the JSON API (`/api/v1`) and the admin
  panel (`/admin`).
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

Aligner arguments are the ones used by the original server, so results stay comparable.

Security measures: aligners are called without a shell and receive no secrets, uploads are
validated and size-limited, result URLs are random UUIDs, admin actions are CSRF-checked, the
site is served with a strict Content Security Policy, and the app containers run as a non-root
user with all Linux capabilities dropped.

## Developing

Requirements: Docker with Compose v2, and [uv](https://docs.astral.sh/uv/) for running checks
outside containers. Start the stack as in [Try it locally](#try-it-locally); the web container
reloads on code changes.

```sh
# Everything, including the real aligners, inside the worker image:
COMPOSE_FILE=compose.yaml docker compose --profile test run --rm --build test

# Fast loop on the host (tests marked `db` need DATABASE_URL, `tools` need the aligners):
cd app
uv sync
DATABASE_URL=postgresql+psycopg://wpsboot:<password>@127.0.0.1:55432/wpsboot_test uv run pytest
uv run ruff check src tests migrations && uv run ruff format --check src tests migrations
SECRET_KEY=dev-secret-key-0123456789 uv run mypy
```

GitHub Actions runs the same lint, type check and container tests on every push to `master` or
`v2` and on pull requests.

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
docs/             deployment guide and project progress (Traditional Chinese)
```

## History

The original 2019 server (Flask + uWSGI) is kept under the `v1-legacy` git tag. Version 2 is a
rewrite with the same aligners, arguments and `concatenate.pl`, packaged with Docker Compose.
Project status and open decisions: [docs/PROGRESS.md](docs/PROGRESS.md).

## References

- Original paper: [Bioinformatics, btz082](https://doi.org/10.1093/bioinformatics/btz082)
- Web page reference: [T-Coffee](http://tcoffee.crg.cat/apps/tcoffee/do:regular)

## Contact

Dr. Jia-Ming Chang, Department of Computer Science, National Chengchi University —
chang.jiaming@gmail.com — http://www.changlabtw.com/
