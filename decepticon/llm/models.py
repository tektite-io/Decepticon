"""LLM model definitions — per-role model assignments with fallbacks.

Each agent role gets a primary model and optional fallback. The assignments
reflect agent characteristics and leverage the latest models (March 2026):

Ensemble strategy:
  - Orchestrator:  Claude Opus 4.6 — strongest reasoning for strategic kill chain
                   coordination, adaptive re-planning, and multi-agent delegation.
                   Fallback: GPT-5.4 (comparable reasoning, cross-provider resilience).

  - Planner:       Claude Opus 4.6 — legal-precision document generation (RoE, CONOPS,
                   OPPLAN). Requires strong structured output and schema adherence.
                   Fallback: GPT-5.4 (strong writing, 1M context).

  - Exploit:       Claude Sonnet 4.6 — high-precision attack path selection with
                   excellent tool calling for exploit frameworks. Opus overkill for
                   tool-heavy sequential execution; Sonnet balances precision + speed.
                   Fallback: GPT-4.1 (strong tool use, 1M context, cost-efficient).

  - Recon:         Claude Haiku 4.5 — best cost-efficiency for high-volume scanning
                   (nmap, nuclei, subfinder) at $1/$5 per MTok. Anthropic-first for
                   Cybench-proven cybersecurity capability and prompt caching synergy.
                   Fallback: Gemini 2.5 Flash (cross-provider, fastest tool calling).

  - PostExploit:   Claude Sonnet 4.6 — iterative lateral movement loop needs strong
                   reasoning + tool calling. Runs many iterations so cost matters.
                   Fallback: GPT-4.1 (strong tool use, cost-efficient at $2/M input).

Model names use LiteLLM provider-prefix format for direct proxy routing.
Fallbacks activate via ModelFallbackMiddleware on API failure (outage, rate limit).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ProxyConfig(BaseModel):
    """LiteLLM proxy connection settings."""

    url: str = "http://localhost:4000"
    api_key: str = "sk-decepticon-master"
    timeout: int = 120
    max_retries: int = 2


class ModelAssignment(BaseModel):
    """Primary + fallback model for an agent role."""

    primary: str
    fallback: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")
        return v


class LLMModelMapping(BaseModel):
    """Role → model assignment mapping.

    Model names use LiteLLM provider-prefix format for direct routing.
    """

    # ── Strategic tier ──────────────────────────────────────────────
    # Reasoning-heavy, few iterations, quality > cost

    decepticon: ModelAssignment = Field(
        default_factory=lambda: ModelAssignment(
            # Opus 4.6: strongest reasoning for kill chain orchestration,
            # adaptive re-planning, and sub-agent delegation decisions.
            # 1M context + prompt caching for long orchestration sessions.
            primary="anthropic/claude-opus-4-6",
            # GPT-5.4: comparable frontier reasoning, cross-provider resilience.
            # 1M context, configurable reasoning effort.
            fallback="openai/gpt-5.4",
            temperature=0.4,
        )
    )

    planning: ModelAssignment = Field(
        default_factory=lambda: ModelAssignment(
            # Opus 4.6: legal-precision document generation (RoE, CONOPS, OPPLAN).
            # Excellent structured output, schema validation, interview skills.
            primary="anthropic/claude-opus-4-6",
            # GPT-5.4: strong writing and structured output for document gen.
            fallback="openai/gpt-5.4",
            temperature=0.4,
        )
    )

    # ── Precision tier ──────────────────────────────────────────────
    # High-stakes execution, moderate iterations, precision critical

    exploit: ModelAssignment = Field(
        default_factory=lambda: ModelAssignment(
            # Sonnet 4.6: strong reasoning + excellent tool calling for exploit
            # frameworks (sqlmap, Impacket, Certipy). Balances precision and speed
            # better than Opus for sequential tool-heavy execution.
            primary="anthropic/claude-sonnet-4-6",
            # GPT-4.1: strong tool use, 1M context, cost-efficient ($2/M input).
            # Good at parsing exploit output and iterating.
            fallback="openai/gpt-4.1",
            temperature=0.3,
        )
    )

    # ── Tactical tier ───────────────────────────────────────────────
    # Tool-heavy, many iterations, speed + cost efficiency matter

    recon: ModelAssignment = Field(
        default_factory=lambda: ModelAssignment(
            # Haiku 4.5: best cost-efficiency for high-volume scanning ($1/$5 per MTok).
            # Matches Sonnet 4 performance on agent/tool-use tasks. 200K context
            # sufficient with output offloading. Anthropic-first for Cybench-proven
            # cybersecurity capability and prompt caching synergy.
            primary="anthropic/claude-haiku-4-5",
            # Gemini 2.5 Flash: cross-provider fallback, fastest tool calling,
            # 1M context for large scan outputs ($0.30/M input).
            fallback="gemini/gemini-2.5-flash",
            temperature=0.3,
        )
    )

    postexploit: ModelAssignment = Field(
        default_factory=lambda: ModelAssignment(
            # Sonnet 4.6: strong reasoning + tool calling for iterative
            # lateral movement loop. Balances quality and cost for the
            # 5-20+ iterations typical in post-exploitation.
            primary="anthropic/claude-sonnet-4-6",
            # GPT-4.1: strong tool use, cost-efficient for many iterations.
            # 1M context handles growing credential inventories.
            fallback="openai/gpt-4.1",
            temperature=0.3,
        )
    )

    def get_assignment(self, role: str) -> ModelAssignment:
        """Get model assignment for a role.

        Raises KeyError if role not found.
        """
        if not hasattr(self, role):
            raise KeyError(f"No model assignment for role: {role}")
        return getattr(self, role)
