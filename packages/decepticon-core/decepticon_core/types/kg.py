"""KnowledgeGraph — Neo4j-native attack graph.

Models the full attack surface as a directed graph with typed nodes and
edges. Node labels map 1-to-1 with Neo4j labels (PascalCase); edge kinds
map to Neo4j relationship types (UPPER_CASE).  The in-memory
:class:`KnowledgeGraph` remains useful for testing and Python-side
reasoning while the authoritative store lives in Neo4j.

Schema
------
Nodes span seven layers — Infrastructure (Host, Network, Domain, Service,
URL, CloudResource, Container), Identity (User, Group, Credential, Secret,
Session), Vulnerability (Vulnerability, CVE, Misconfiguration, Weakness),
Code (Repository, SourceFile, CodeLocation, Contract), Attack Progression
(Technique, Entrypoint, CrownJewel, AttackPath, Finding), Analysis
(Candidate, Hypothesis, Patch), and Defense (DetectionFired, DefenseAction).

Edges carry a ``kind`` (Neo4j relationship type) plus optional ``weight``
used by the path planner (lower = easier exploitation).

Design goals
------------
1. **Append-mostly**: agents write once, read often. Deduplication via
   deterministic node IDs (SHA1 of kind + canonical key).
2. **Schema validation**: Pydantic models reject bad writes at the boundary.
3. **Queryable**: ``neighbors()``, ``by_kind()``, ``find()`` support
   Python-side reasoning. O(N) is fine at engagement scale (<10K nodes).
4. **Neo4j-native labels**: ``NodeKind`` values are PascalCase and used
   directly as Neo4j node labels. ``EdgeKind`` values are UPPER_CASE and
   used directly as Neo4j relationship types.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable, Iterator
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── Enumerations ────────────────────────────────────────────────────────


class NodeKind(StrEnum):
    """Canonical node types in the research graph.

    Values are PascalCase to match Neo4j node labels directly.
    """

    # Infrastructure
    HOST = "Host"
    NETWORK = "Network"
    DOMAIN = "Domain"
    SERVICE = "Service"
    URL = "URL"
    CLOUD_RESOURCE = "CloudResource"
    CONTAINER = "Container"
    # Identity
    USER = "User"
    GROUP = "Group"
    CREDENTIAL = "Credential"
    SECRET = "Secret"
    SESSION = "Session"
    # Vulnerability
    VULNERABILITY = "Vulnerability"
    CVE = "CVE"
    MISCONFIGURATION = "Misconfiguration"
    WEAKNESS = "Weakness"
    # Code
    REPOSITORY = "Repository"
    SOURCE_FILE = "SourceFile"
    CODE_LOCATION = "CodeLocation"
    CONTRACT = "Contract"
    # Attack Progression
    TECHNIQUE = "Technique"
    ENTRYPOINT = "Entrypoint"
    CROWN_JEWEL = "CrownJewel"
    ATTACK_PATH = "AttackPath"
    FINDING = "Finding"
    # Analysis
    CANDIDATE = "Candidate"
    HYPOTHESIS = "Hypothesis"
    PATCH = "Patch"
    # Defense (Blue Cell — proven detection coverage)
    DETECTION_FIRED = "DetectionFired"
    DEFENSE_ACTION = "DefenseAction"
    # Active Directory (BloodHound 5.x — see
    # docs/design/2026-06-04-bloodhound-kgstore-mapping.md). AD-prefixed
    # kinds coexist with the generic identity kinds above; the
    # AD operator's BloodHound ingest emits these, and chain analysis
    # filters with ``MATCH (u:ADUser)-[:MEMBER_OF*]->(:ADGroup ...)``.
    AD_USER = "ADUser"
    AD_COMPUTER = "ADComputer"
    AD_GROUP = "ADGroup"
    AD_DOMAIN = "ADDomain"
    AD_GPO = "ADGPO"
    AD_OU = "ADOU"
    AD_CONTAINER = "ADContainer"
    AD_CERT_TEMPLATE = "ADCertTemplate"
    AD_ENTERPRISE_CA = "ADEnterpriseCA"
    AD_ROOT_CA = "ADRootCA"
    AD_AIA_CA = "ADAIACA"
    AD_NT_AUTH_STORE = "ADNTAuthStore"
    AD_ISSUANCE_POLICY = "ADIssuancePolicy"
    AD_LOCAL_GROUP = "ADLocalGroup"
    # Solidity (Slither ``--json`` — see
    # docs/design/2026-06-04-slither-kgstore-mapping.md). ``Contract`` and
    # ``SourceFile`` are already defined above and reused.
    SOLIDITY_FUNCTION = "Function"
    SOLIDITY_STATE_VAR = "StateVar"
    SOLIDITY_EVENT = "Event"
    SOLIDITY_CUSTOM_ERROR = "CustomError"
    SOLIDITY_ENUM = "Enum"
    SOLIDITY_STRUCT = "Struct"
    SOLIDITY_PRAGMA = "Pragma"


class EdgeKind(StrEnum):
    """Canonical edge types — describe how nodes relate.

    Values are UPPER_CASE to match Neo4j relationship type conventions.
    """

    # Topology
    HOSTS = "HOSTS"
    RESOLVES_TO = "RESOLVES_TO"
    CONTAINS = "CONTAINS"
    EXPOSES = "EXPOSES"
    ROUTES_TO = "ROUTES_TO"
    PART_OF = "PART_OF"
    MANAGES = "MANAGES"
    # Access
    AUTHENTICATES_TO = "AUTHENTICATES_TO"
    HAS_SESSION = "HAS_SESSION"
    MEMBER_OF = "MEMBER_OF"
    CAN_ACCESS = "CAN_ACCESS"
    ADMIN_TO = "ADMIN_TO"
    OWNS = "OWNS"
    GRANTS = "GRANTS"
    # Exploitation
    AFFECTS = "AFFECTS"
    HAS_VULN = "HAS_VULN"
    EXPLOITS = "EXPLOITS"
    ENABLES = "ENABLES"
    LEAKS = "LEAKS"
    LEADS_TO = "LEADS_TO"
    DEFINED_IN = "DEFINED_IN"
    INSTANCE_OF = "INSTANCE_OF"
    # Kill Chain
    PIVOTS_TO = "PIVOTS_TO"
    ESCALATES_TO = "ESCALATES_TO"
    REACHES = "REACHES"
    STARTS_AT = "STARTS_AT"
    STEP = "STEP"
    USES = "USES"
    # Validation
    VALIDATES = "VALIDATES"
    DERIVED_FROM = "DERIVED_FROM"
    PATCHES = "PATCHES"
    MAPS_TO = "MAPS_TO"
    # Defense (Blue Cell — links a fired detection to what it caught)
    DETECTED = "DETECTED"
    USES_RULE = "USES_RULE"
    # Active Directory (BloodHound 5.x — see
    # docs/design/2026-06-04-bloodhound-kgstore-mapping.md). The generic
    # ``MEMBER_OF`` / ``HAS_SESSION`` / ``ADMIN_TO`` / ``OWNS`` /
    # ``CAN_ACCESS`` above are reused where the BHCE edge name matches.
    ALLOWED_TO_DELEGATE = "ALLOWED_TO_DELEGATE"
    ALLOWED_TO_ACT = "ALLOWED_TO_ACT"
    HAS_SID_HISTORY = "HAS_SID_HISTORY"
    GP_LINK = "GP_LINK"
    PUBLISHED_TO = "PUBLISHED_TO"
    HOSTS_CA_SERVICE = "HOSTS_CA_SERVICE"
    OID_GROUP_LINK = "OID_GROUP_LINK"
    ROOT_CA_FOR = "ROOT_CA_FOR"
    ISSUED_SIGNED_BY = "ISSUED_SIGNED_BY"
    TRUSTED_FOR_NTAUTH = "TRUSTED_FOR_NTAUTH"
    DUMP_SMSA_PASSWORD = "DumpSMSAPassword"
    MEMBER_OF_LOCAL_GROUP = "MEMBER_OF_LOCAL_GROUP"
    # Trust (4-way split from BHCE 5.x — replaces the single legacy
    # ``TrustedBy`` edge, branched on ``TrustType`` + ``IsTransitive``).
    SAME_FOREST_TRUST = "SameForestTrust"
    CROSS_FOREST_TRUST = "CrossForestTrust"
    ABUSE_TGT_DELEGATION = "AbuseTGTDelegation"
    SPOOF_SID_HISTORY = "SpoofSIDHistory"
    # ADCS ESC — server-computed post-process edges. ESC2/5/7/8/11/12/
    # 14/15/16 are placeholders for community-collector parity
    # (Certipy etc.); BHCE main 2026-06 does not emit them yet but the
    # data path is ready.
    ADCS_ESC1 = "ADCSESC1"
    ADCS_ESC2 = "ADCSESC2"
    ADCS_ESC3 = "ADCSESC3"
    ADCS_ESC4 = "ADCSESC4"
    ADCS_ESC5 = "ADCSESC5"
    ADCS_ESC6A = "ADCSESC6a"
    ADCS_ESC6B = "ADCSESC6b"
    ADCS_ESC7 = "ADCSESC7"
    ADCS_ESC8 = "ADCSESC8"
    ADCS_ESC9A = "ADCSESC9a"
    ADCS_ESC9B = "ADCSESC9b"
    ADCS_ESC10A = "ADCSESC10a"
    ADCS_ESC10B = "ADCSESC10b"
    ADCS_ESC11 = "ADCSESC11"
    ADCS_ESC12 = "ADCSESC12"
    ADCS_ESC13 = "ADCSESC13"
    ADCS_ESC14 = "ADCSESC14"
    ADCS_ESC15 = "ADCSESC15"
    ADCS_ESC16 = "ADCSESC16"
    # AD post-process edges (BHCE-server-computed).
    GOLDEN_CERT = "GoldenCert"
    SYNC_LAPS_PASSWORD = "SyncLAPSPassword"
    DCSYNC = "DCSync"
    COERCE_AND_RELAY_NTLM_TO_ADCS = "CoerceAndRelayNTLMToADCS"
    COERCE_AND_RELAY_NTLM_TO_LDAP = "CoerceAndRelayNTLMToLDAP"
    COERCE_AND_RELAY_NTLM_TO_LDAPS = "CoerceAndRelayNTLMToLDAPS"
    COERCE_AND_RELAY_NTLM_TO_SMB = "CoerceAndRelayNTLMToSMB"
    COERCE_TO_TGT = "CoerceToTGT"
    HAS_TRUST_KEYS = "HasTrustKeys"
    SYNCED_TO_ENTRA_USER = "SyncedToEntraUser"
    SYNCED_TO_AD_USER = "SyncedToADUser"
    # ACE right names (raw forms — ``Owns`` / ``WriteOwner`` are emitted
    # by post-process as the existing ``OWNS`` / ``WRITE_OWNER`` kinds).
    WRITE_SPN = "WriteSPN"
    READ_LAPS_PASSWORD = "ReadLAPSPassword"
    READ_GMSA_PASSWORD = "ReadGMSAPassword"
    ADD_KEY_CREDENTIAL_LINK = "AddKeyCredentialLink"
    ALL_EXTENDED_RIGHTS = "AllExtendedRights"
    FORCE_CHANGE_PASSWORD = "ForceChangePassword"
    MANAGE_CA = "ManageCA"
    MANAGE_CERTIFICATES = "ManageCertificates"
    GET_CHANGES = "GetChanges"
    GET_CHANGES_ALL = "GetChangesAll"
    OWNS_LIMITED_RIGHTS = "OwnsLimitedRights"
    WRITE_OWNER_LIMITED_RIGHTS = "WriteOwnerLimitedRights"
    WRITE_DACL = "WriteDacl"
    WRITE_OWNER = "WriteOwner"
    GENERIC_ALL = "GenericAll"
    GENERIC_WRITE = "GenericWrite"
    ADD_MEMBER = "AddMember"
    ADD_SELF = "AddSelf"
    WRITE_GP_LINK = "WriteGPLink"
    WRITE_ACCOUNT_RESTRICTIONS = "WriteAccountRestrictions"
    # Solidity (Slither) — function-call graph edge.
    CALLS = "CALLS"


class Severity(StrEnum):
    """CVSS-style qualitative severity."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_SCORE: dict[Severity, float] = {
    Severity.INFO: 0.0,
    Severity.LOW: 3.0,
    Severity.MEDIUM: 5.5,
    Severity.HIGH: 7.5,
    Severity.CRITICAL: 9.5,
}


SEVERITY_COST_MULTIPLIER: dict[Severity, float] = {
    Severity.CRITICAL: 0.4,
    Severity.HIGH: 0.6,
    Severity.MEDIUM: 1.0,
    Severity.LOW: 1.6,
    Severity.INFO: 2.5,
}


# ── Models ──────────────────────────────────────────────────────────────


class Node(BaseModel):
    """A node in the knowledge graph."""

    id: str
    kind: NodeKind
    label: str
    props: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    @classmethod
    def make(cls, kind: NodeKind, label: str, **props: Any) -> Node:
        """Construct a node with a deterministic ID derived from ``kind + label``.

        Same (kind, label) always hashes to the same ID — this is how we
        dedupe agent writes without needing a database. ``props`` contributes
        to the hash only through the ``key`` field if provided, letting
        callers supply an explicit dedup key (e.g. normalized URL).
        """
        key = props.get("key", label)
        digest = hashlib.sha1(f"{kind.value}::{key}".encode(), usedforsecurity=False).hexdigest()[
            :16
        ]
        return cls(id=digest, kind=kind, label=label, props=dict(props))


class Edge(BaseModel):
    """A directed edge in the knowledge graph."""

    id: str
    src: str
    dst: str
    kind: EdgeKind
    weight: float = 1.0
    props: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)

    @classmethod
    def make(
        cls,
        src: str,
        dst: str,
        kind: EdgeKind,
        weight: float = 1.0,
        **props: Any,
    ) -> Edge:
        # ``key`` in props participates in the deterministic edge ID so
        # multiple edges of the same kind between the same (src, dst)
        # can coexist (e.g. AD GetChanges + GetChangesAll both mapped
        # to LEAKS but semantically distinct).
        key = props.get("key", "")
        digest = hashlib.sha1(
            f"{src}->{kind.value}->{dst}::{key}".encode(), usedforsecurity=False
        ).hexdigest()[:16]
        return cls(id=digest, src=src, dst=dst, kind=kind, weight=weight, props=dict(props))


# ── Graph ───────────────────────────────────────────────────────────────


class KnowledgeGraph(BaseModel):
    """In-memory engagement knowledge graph.

    Provides typed node/edge storage with query helpers for Python-side
    reasoning.  The authoritative persistence backend is Neo4j; this class
    is used for testing, batch construction, and agent-local caching.
    """

    nodes: dict[str, Node] = Field(default_factory=dict)
    edges: dict[str, Edge] = Field(default_factory=dict)
    version: int = 1

    # ── mutators ──────────────────────────────────────────────────────

    def upsert_node(self, node: Node) -> Node:
        """Insert or update a node, merging props on update."""
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
            return node
        # Merge — new props win, but keep created_at
        merged_props = {**existing.props, **node.props}
        existing.props = merged_props
        existing.label = node.label  # accept relabel
        existing.updated_at = time.time()
        return existing

    def upsert_edge(self, edge: Edge) -> Edge:
        """Insert or update an edge (weight is overwritten on re-insert)."""
        existing = self.edges.get(edge.id)
        if existing is None:
            self.edges[edge.id] = edge
            return edge
        existing.weight = edge.weight
        existing.props = {**existing.props, **edge.props}
        return existing

    def remove_node(self, node_id: str) -> int:
        """Remove a node and all edges touching it. Returns total removed count."""
        removed = 0
        if node_id in self.nodes:
            del self.nodes[node_id]
            removed += 1
        to_drop = [eid for eid, e in self.edges.items() if e.src == node_id or e.dst == node_id]
        for eid in to_drop:
            del self.edges[eid]
            removed += 1
        return removed

    # ── queries ───────────────────────────────────────────────────────

    def by_kind(self, kind: NodeKind) -> list[Node]:
        """All nodes of the given kind, ordered by creation time."""
        return sorted(
            (n for n in self.nodes.values() if n.kind == kind),
            key=lambda n: n.created_at,
        )

    def find(self, kind: NodeKind | None = None, **props: Any) -> list[Node]:
        """Find nodes matching kind and all provided prop equality constraints."""
        matches: list[Node] = []
        for node in self.nodes.values():
            if kind is not None and node.kind != kind:
                continue
            if all(node.props.get(k) == v for k, v in props.items()):
                matches.append(node)
        return matches

    def neighbors(
        self,
        node_id: str,
        edge_kind: EdgeKind | None = None,
        direction: str = "out",
    ) -> list[tuple[Edge, Node]]:
        """Return (edge, neighbor) pairs for a node.

        direction: "out" (src=node), "in" (dst=node), or "both".
        """
        if direction not in ("out", "in", "both"):
            raise ValueError("direction must be out/in/both")
        result: list[tuple[Edge, Node]] = []
        for edge in self.edges.values():
            if edge_kind is not None and edge.kind != edge_kind:
                continue
            if direction in ("out", "both") and edge.src == node_id:
                nbr = self.nodes.get(edge.dst)
                if nbr is not None:
                    result.append((edge, nbr))
            if direction in ("in", "both") and edge.dst == node_id:
                nbr = self.nodes.get(edge.src)
                if nbr is not None:
                    result.append((edge, nbr))
        return result

    def adjacency(self) -> dict[str, list[tuple[str, Edge]]]:
        """Build an adjacency list for graph search (out-edges only)."""
        adj: dict[str, list[tuple[str, Edge]]] = {nid: [] for nid in self.nodes}
        for edge in self.edges.values():
            if edge.src in adj and edge.dst in self.nodes:
                adj[edge.src].append((edge.dst, edge))
        return adj

    def stats(self) -> dict[str, int]:
        """High-level counts used for status displays and tests."""
        counts: dict[str, int] = {"nodes": len(self.nodes), "edges": len(self.edges)}
        for node in self.nodes.values():
            counts[f"node.{node.kind.value}"] = counts.get(f"node.{node.kind.value}", 0) + 1
        for edge in self.edges.values():
            counts[f"edge.{edge.kind.value}"] = counts.get(f"edge.{edge.kind.value}", 0) + 1
        return counts

    # ── severity helpers ──────────────────────────────────────────────

    def vulnerabilities_by_severity(self, min_severity: Severity = Severity.LOW) -> list[Node]:
        """Return vuln nodes with severity >= ``min_severity``, highest first."""
        threshold = SEVERITY_SCORE[min_severity]
        vulns: list[Node] = []
        for node in self.by_kind(NodeKind.VULNERABILITY):
            sev = Severity(node.props.get("severity", Severity.INFO))
            if SEVERITY_SCORE[sev] >= threshold:
                vulns.append(node)
        vulns.sort(
            key=lambda n: SEVERITY_SCORE[Severity(n.props.get("severity", Severity.INFO))],
            reverse=True,
        )
        return vulns

    # ── batch helpers ─────────────────────────────────────────────────

    def bulk_upsert_nodes(self, nodes: Iterable[Node]) -> int:
        count = 0
        for node in nodes:
            self.upsert_node(node)
            count += 1
        return count

    def bulk_upsert_edges(self, edges: Iterable[Edge]) -> int:
        count = 0
        for edge in edges:
            self.upsert_edge(edge)
            count += 1
        return count

    def iter_paths(self, src: str, dst: str, max_depth: int = 6) -> Iterator[list[str]]:
        """Enumerate simple paths from src to dst (bounded depth).

        Used by the chain planner for exploration but exposed here so
        callers can build custom scoring without pulling the planner in.
        """
        if src not in self.nodes or dst not in self.nodes:
            return
        adj = self.adjacency()
        stack: list[tuple[str, list[str]]] = [(src, [src])]
        while stack:
            cur, path = stack.pop()
            if len(path) > max_depth:
                continue
            if cur == dst and len(path) > 1:
                yield list(path)
                continue
            for nxt, _edge in adj.get(cur, []):
                if nxt in path:
                    continue
                stack.append((nxt, path + [nxt]))
