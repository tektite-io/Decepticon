"""ADCS post-process — BHCE-server-equivalent edge synthesis.

BloodHound CE's server walks the ingested raw graph and synthesises
the high-signal attack edges (``DCSync``, ``GoldenCert``,
``ADCS_ESC1`` … ``ESC13``, etc.) that chain planners actually
reason about. The Decepticon ingest in ``bloodhound.py`` only writes
the raw collector data; this module is where the synthesis runs.

Scope of this first cut (intentionally narrow — see the BloodHound
RFC §4.3 for the full plan):

  - **``DCSync``**: A principal that holds both ``GET_CHANGES`` and
    ``GET_CHANGES_ALL`` on a Domain has effective DCSync rights.
    BHCE collapses the pair into a single ``DCSync`` edge per
    (principal, domain) pair.
  - **``GoldenCert``**: A principal that holds ``OWNS`` /
    ``WRITE_OWNER`` / ``MANAGE_CA`` on an EnterpriseCA can issue
    arbitrary certificates as that CA — a forged-trust-anchor
    primitive. We mint one ``GoldenCert`` edge per principal +
    EnterpriseCA pair.

ESC1/3/4/6a/6b/9a/9b/10a/10b/13 require Enroll edges (raw ACE
right-name) that the current ingest does not yet emit — they land
in a dedicated follow-up PR alongside Enroll ingest.

The synthesis is **idempotent**: each ``MERGE`` keys on the
(principal, target) pair so re-running the post-process produces no
extra edges. Each new edge carries ``post_process_source`` props so
analysts can distinguish synthesised edges from raw ACE data.
"""

from __future__ import annotations

from dataclasses import dataclass

from decepticon.middleware.kg_internal.store import KGStore


@dataclass
class PostProcessStats:
    """Counts of edges created per algorithm. Re-runs return zero for
    every value because each ``MERGE`` is idempotent."""

    dcsync: int = 0
    golden_cert: int = 0

    def to_dict(self) -> dict[str, int]:
        return self.__dict__


# Cypher templates — kept short + auditable so the algorithm is
# obvious to reviewers without hunting through string concatenation.

# ``r._jc`` is a transient marker the MERGE writes on the create path
# and clears on the match path; counting it gives the true new-edge
# count. ``count(r)`` instead returns the total ``MATCH``ed count
# (always ≥ 1 after the first run) and breaks idempotency reporting.
# Same trick the node-write path in ``record_observations`` uses.

_DCSYNC_QUERY = (
    "MATCH (p)-[gc:GET_CHANGES {engagement: $engagement}]->(d:Domain {engagement: $engagement}) "
    "MATCH (p)-[gca:GET_CHANGES_ALL {engagement: $engagement}]->(d) "
    "MERGE (p)-[r:DCSYNC {engagement: $engagement}]->(d) "
    "ON CREATE SET r.firstseen = $now, "
    "              r.created_by = $created_by, "
    "              r.source_episode_id = $source_episode_id, "
    "              r.post_process_source = 'GetChanges+GetChangesAll', "
    "              r._jc = true "
    "ON MATCH SET r._jc = false "
    "SET r.lastupdated = $now "
    "WITH r, r._jc AS just_created "
    "REMOVE r._jc "
    "RETURN sum(CASE WHEN just_created THEN 1 ELSE 0 END) AS created"
)

_GOLDEN_CERT_QUERY = (
    "MATCH (p)-[r:OWNS|WRITE_OWNER|MANAGE_CA {engagement: $engagement}]->"
    "(ca:ADEnterpriseCA {engagement: $engagement}) "
    "WITH DISTINCT p, ca "
    "MERGE (p)-[gc:GOLDEN_CERT {engagement: $engagement}]->(ca) "
    "ON CREATE SET gc.firstseen = $now, "
    "              gc.created_by = $created_by, "
    "              gc.source_episode_id = $source_episode_id, "
    "              gc.post_process_source = 'Owns|WriteOwner|ManageCA on EnterpriseCA', "
    "              gc._jc = true "
    "ON MATCH SET gc._jc = false "
    "SET gc.lastupdated = $now "
    "WITH gc, gc._jc AS just_created "
    "REMOVE gc._jc "
    "RETURN sum(CASE WHEN just_created THEN 1 ELSE 0 END) AS created"
)


def synthesise_adcs_post(
    *,
    engagement: str,
    store: KGStore | None = None,
    source_episode_id: str = "adcs_post",
    created_by: str = "adcs_post",
) -> PostProcessStats:
    """Run every post-process synthesis algorithm in this module
    against ``engagement``.

    Args:
        engagement: Engagement label whose raw graph to walk.
        store: Optional pre-constructed ``KGStore`` for tests; defaults
            to ``KGStore.from_env()`` and is closed before return.
        source_episode_id: Provenance tag attached to every synthesised
            edge so analysts can distinguish post-process output from
            raw ACE data.
        created_by: ``created_by`` provenance prop (defaults to
            ``adcs_post`` so it sorts visibly next to ``bh_ingest``).

    Returns:
        :class:`PostProcessStats` with per-algorithm counts of edges
        the synthesis created **this run** (excluding ones that were
        already present and only re-touched).
    """
    import time

    now = int(time.time())
    owned_store = store is None
    target_store = store if store is not None else KGStore.from_env()

    stats = PostProcessStats()
    try:
        # DCSync
        rows = target_store.execute_write(
            _DCSYNC_QUERY,
            {
                "engagement": engagement,
                "now": now,
                "created_by": created_by,
                "source_episode_id": source_episode_id,
            },
            engagement=engagement,
        )
        if rows:
            stats.dcsync = int(rows[0].get("created") or 0)

        # GoldenCert
        rows = target_store.execute_write(
            _GOLDEN_CERT_QUERY,
            {
                "engagement": engagement,
                "now": now,
                "created_by": created_by,
                "source_episode_id": source_episode_id,
            },
            engagement=engagement,
        )
        if rows:
            stats.golden_cert = int(rows[0].get("created") or 0)
    finally:
        if owned_store:
            target_store.close()

    return stats
