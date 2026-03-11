# Gevent monkey-patching must happen before any other import so that the
# standard library's socket, threading, and ssl modules are replaced with
# gevent-cooperative equivalents before Flask/SQLAlchemy/Redis import them.
from gevent import monkey  # noqa: E402
monkey.patch_all()

# Patch psycopg2's libpq wait mechanism so DB I/O yields to gevent's event
# loop instead of blocking the whole worker process.
from psycogreen.gevent import patch_psycopg  # noqa: E402
patch_psycopg()

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
