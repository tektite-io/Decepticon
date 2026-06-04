"""KGStore-mock-based tests for ``tools.ad.adcs_post``.

The synthesis runs as raw Cypher inside ``KGStore.execute_write``, so
the unit tests verify the **shape of the calls** (engagement scoping,
provenance threading, query content) — full algorithmic correctness
is covered by the live dogfood against compose Neo4j (the
post-process is fundamentally a graph traversal, not pure Python).
"""

from __future__ import annotations

from typing import Any

from decepticon.tools.ad.adcs_post import (
    PostProcessStats,
    synthesise_adcs_post,
)


class _FakeKGStore:
    """Captures every ``execute_write`` call so tests can inspect the
    queries and parameter shape."""

    def __init__(self, *, dcsync_created: int = 1, golden_created: int = 1) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        self._dcsync_created = dcsync_created
        self._golden_created = golden_created
        self.closed = False

    def execute_write(
        self, query: str, params: dict[str, Any], *, engagement: str
    ) -> list[dict[str, Any]]:
        self.calls.append((query, dict(params), engagement))
        # The two queries differ in their MATCH pattern: DCSync starts
        # with GET_CHANGES, GoldenCert with OWNS|WRITE_OWNER|MANAGE_CA.
        if "GET_CHANGES" in query:
            return [{"created": self._dcsync_created}]
        if "OWNS|WRITE_OWNER|MANAGE_CA" in query:
            return [{"created": self._golden_created}]
        return []

    def close(self) -> None:
        self.closed = True


# ── Public signature contracts ─────────────────────────────────────


class TestPublicSignatures:
    def test_returns_post_process_stats(self) -> None:
        store = _FakeKGStore()
        result = synthesise_adcs_post(
            engagement="t",
            store=store,  # type: ignore[arg-type]
        )
        assert isinstance(result, PostProcessStats)

    def test_stats_carry_counts_from_each_query(self) -> None:
        store = _FakeKGStore(dcsync_created=3, golden_created=2)
        stats = synthesise_adcs_post(
            engagement="t",
            store=store,  # type: ignore[arg-type]
        )
        assert stats.dcsync == 3
        assert stats.golden_cert == 2

    def test_provenance_threaded_into_every_call(self) -> None:
        store = _FakeKGStore()
        synthesise_adcs_post(
            engagement="t-eng",
            store=store,  # type: ignore[arg-type]
            source_episode_id="ep-x",
            created_by="adcs_post_test",
        )
        assert len(store.calls) == 2
        for _query, params, engagement in store.calls:
            assert engagement == "t-eng"
            assert params["engagement"] == "t-eng"
            assert params["created_by"] == "adcs_post_test"
            assert params["source_episode_id"] == "ep-x"

    def test_caller_supplied_store_not_closed(self) -> None:
        """When a caller passes ``store=``, the post-process must NOT
        close it on return — caller owns the lifetime."""
        store = _FakeKGStore()
        synthesise_adcs_post(
            engagement="t",
            store=store,  # type: ignore[arg-type]
        )
        assert store.closed is False


# ── DCSync algorithm ───────────────────────────────────────────────


class TestDcsyncQuery:
    def _dcsync_query(self, store: _FakeKGStore) -> str:
        for q, _params, _engagement in store.calls:
            if "DCSYNC" in q:
                return q
        raise AssertionError("DCSync query not issued")

    def test_dcsync_query_requires_both_get_changes_edges(self) -> None:
        store = _FakeKGStore()
        synthesise_adcs_post(
            engagement="t",
            store=store,  # type: ignore[arg-type]
        )
        q = self._dcsync_query(store)
        # Both rights must MATCH on the same (principal, domain) pair.
        assert ":GET_CHANGES" in q
        assert ":GET_CHANGES_ALL" in q

    def test_dcsync_query_scopes_match_to_engagement(self) -> None:
        store = _FakeKGStore()
        synthesise_adcs_post(
            engagement="t",
            store=store,  # type: ignore[arg-type]
        )
        q = self._dcsync_query(store)
        assert q.count("engagement: $engagement") >= 3  # 2 raw + 1 merged

    def test_dcsync_query_uses_jc_marker_for_idempotent_count(self) -> None:
        store = _FakeKGStore()
        synthesise_adcs_post(
            engagement="t",
            store=store,  # type: ignore[arg-type]
        )
        q = self._dcsync_query(store)
        # The ``_jc`` marker pattern is what makes the run-2 stats
        # truthfully zero. ``count(r)`` would always return ≥ 1 after
        # the first run.
        assert "_jc" in q
        assert "ON CREATE SET" in q and "ON MATCH SET" in q


# ── GoldenCert algorithm ───────────────────────────────────────────


class TestGoldenCertQuery:
    def _golden_query(self, store: _FakeKGStore) -> str:
        for q, _params, _engagement in store.calls:
            if "GOLDEN_CERT" in q:
                return q
        raise AssertionError("GoldenCert query not issued")

    def test_golden_cert_requires_owns_writeowner_or_manageca_on_enterprise_ca(
        self,
    ) -> None:
        store = _FakeKGStore()
        synthesise_adcs_post(
            engagement="t",
            store=store,  # type: ignore[arg-type]
        )
        q = self._golden_query(store)
        # The alternation covers the three rights BHCE promotes to
        # GoldenCert.
        assert ":OWNS|WRITE_OWNER|MANAGE_CA" in q
        # Target must be an EnterpriseCA, not an arbitrary node.
        assert ":ADEnterpriseCA" in q

    def test_golden_cert_query_deduplicates_via_distinct(self) -> None:
        store = _FakeKGStore()
        synthesise_adcs_post(
            engagement="t",
            store=store,  # type: ignore[arg-type]
        )
        q = self._golden_query(store)
        # Without ``WITH DISTINCT``, a principal with multiple rights
        # on the same CA would mint extra GoldenCert edges.
        assert "WITH DISTINCT" in q

    def test_golden_cert_query_uses_jc_marker_for_idempotent_count(self) -> None:
        store = _FakeKGStore()
        synthesise_adcs_post(
            engagement="t",
            store=store,  # type: ignore[arg-type]
        )
        q = self._golden_query(store)
        assert "_jc" in q
        assert "ON CREATE SET" in q and "ON MATCH SET" in q


# ── Default-store path ─────────────────────────────────────────────


class TestDefaultStorePath:
    def test_omitting_store_constructs_from_env(self, monkeypatch) -> None:
        """When the caller omits ``store=``, the helper builds a
        ``KGStore`` via ``from_env`` and closes it before return."""
        constructed: list[_FakeKGStore] = []

        def _fake_from_env() -> _FakeKGStore:  # type: ignore[override]
            s = _FakeKGStore()
            constructed.append(s)
            return s

        monkeypatch.setattr(
            "decepticon.tools.ad.adcs_post.KGStore.from_env",
            staticmethod(_fake_from_env),
        )

        synthesise_adcs_post(engagement="t")
        assert len(constructed) == 1
        assert constructed[0].closed is True
