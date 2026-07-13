FROM python:3.11-slim

# ---------------------------------------------------------------------------
# System packages
#   build-essential  – gcc/g++ needed to compile gevent's C extensions
#   libev-dev        – gevent event loop (libev backend)
#   libffi-dev       – cryptography package
#   libxml2-dev + libxslt1-dev – readability-lxml (briefing ingestion)
#   curl             – used below to install Node.js 20 LTS, then removed
#   postgresql-client – pg_dump for scripts/backup_neon_to_s3.py (Render cron)
# psycopg2-binary bundles libpq so no libpq-dev needed at runtime.
# ---------------------------------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libev-dev \
        libffi-dev \
        libxml2-dev \
        libxslt1-dev \
        libgomp1 \
        libopenblas0 \
        postgresql-client \
        curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies — this layer is re-used by Docker cache until
# requirements.txt changes, so expensive pip compilation only re-runs when
# a dependency actually changes.
COPY requirements.txt .
# Force cryptography>=48.0.1 after resolve: atproto still caps <47 but
# GHSA-537c-gmf6-5ccf is fixed only in 48.0.1 (see requirements.txt comment).
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt \
    && pip install --no-cache-dir --force-reinstall --no-deps 'cryptography>=48.0.1,<50'

# Node dependencies — cached until package.json / package-lock.json change
COPY package.json package-lock.json* ./
RUN npm install --silent

# Application source (comes last so code changes don't bust the dep layers)
COPY . .

# Compile Flask-Babel translation catalogs (.po → .mo)
# Must run after COPY so the .po source files are available.
RUN pybabel compile -d translations

# Build Tailwind CSS (production-minified output)
RUN npx tailwindcss \
        -i ./app/static/src/input.css \
        -o ./app/static/css/output.css \
        --minify

# Gunicorn binds to 5000; render.yaml exposes this via PORT=5000.
EXPOSE 5000

CMD ["gunicorn", "-c", "gunicorn_config.py", "run:app"]
