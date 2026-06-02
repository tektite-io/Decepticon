"""``python -m decepticon.skillogy`` — run the Skillogy server.

Phase 1a (Amendment v0.2.2) boot sequence:

1. Build a ``Neo4jBackend`` against the configured Bolt URI (waits for
   the graph to be reachable; the compose ``depends_on: neo4j (healthy)``
   gating means it should already be up).
2. Optionally ingest the CI-built ``skills.cypher`` dump into Neo4j so
   a fresh container boot ends up with the corpus loaded (idempotent —
   the builder emits only ``MERGE`` statements).
3. Start the FastAPI REST app on ``$SKILLOGY_REST_PORT``.

Environment variables:
  SKILLOGY_REST_PORT          (default 9100)
  SKILLOGY_NEO4J_URI          (default ``bolt://neo4j:7687``)
  SKILLOGY_NEO4J_USER         (default ``neo4j``)
  SKILLOGY_NEO4J_PASSWORD     (default ``decepticon-graph``)
  SKILLOGY_CYPHER_PATH        (default ``/app/skills.cypher`` — baked into the image)
  SKILLOGY_AUTO_INGEST        (default ``1``; set ``0`` to skip the bulk load)
  SKILLOGY_API_KEY            (optional Bearer-token auth for the protected endpoints)
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

from decepticon.skillogy.server.app import build_app
from decepticon.skillogy.server.neo4j_backend import Neo4jBackend

log = logging.getLogger("skillogy")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _build_backend() -> Neo4jBackend:
    return Neo4jBackend(
        uri=os.environ.get("SKILLOGY_NEO4J_URI", "bolt://neo4j:7687"),
        user=os.environ.get("SKILLOGY_NEO4J_USER", "neo4j"),
        password=os.environ.get("SKILLOGY_NEO4J_PASSWORD", "decepticon-graph"),
    )


def _maybe_ingest(backend: Neo4jBackend) -> None:
    if os.environ.get("SKILLOGY_AUTO_INGEST", "1").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        log.info("SKILLOGY_AUTO_INGEST disabled; skipping cypher load")
        return
    cypher_path = Path(os.environ.get("SKILLOGY_CYPHER_PATH", "/app/skills.cypher"))
    if not cypher_path.exists():
        log.warning(
            "skills.cypher not found at %s; serving an empty graph until "
            "the operator ingests something else",
            cypher_path,
        )
        return
    cypher_text = cypher_path.read_text(encoding="utf-8")
    n = backend.bulk_ingest_cypher(cypher_text)
    log.info("ingested %d Cypher statements from %s", n, cypher_path)


def _start_rest(backend: Neo4jBackend, port: int, started_at: float) -> None:
    try:
        import uvicorn  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "Skillogy REST requires uvicorn. Install with: pip install uvicorn"
        ) from exc
    app = build_app(backend, started_at=started_at)
    # 0.0.0.0 is intentional: the Skillogy container is only exposed on
    # decepticon-net; docker-compose pins the host port to 127.0.0.1.
    config = uvicorn.Config(  # nosec B104
        app=app, host="0.0.0.0", port=port, log_level="info"
    )
    uvicorn.Server(config).run()


def main() -> int:
    _setup_logging()
    rest_port = int(os.environ.get("SKILLOGY_REST_PORT", "9100"))

    backend = _build_backend()
    started_at = time.time()

    try:
        _maybe_ingest(backend)
    except Exception as exc:  # noqa: BLE001
        # Failing to ingest is loud but not fatal — the operator may
        # be running against a Neo4j that was pre-loaded out of band
        # (a different cypher file, or a manual seed). REST stays up so
        # health probes can report the situation.
        log.error("cypher ingest failed: %r — continuing without it", exc)

    def _handle_term(_signum, _frame):
        log.info("SIGTERM received; closing backend and exiting")
        try:
            backend.close()
        finally:
            sys.exit(0)

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_term)

    _start_rest(backend, rest_port, started_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
