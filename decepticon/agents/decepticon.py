"""Decepticon Orchestrator — autonomous red team coordinator.

Uses create_agent() directly (not create_deep_agent()) to control the
middleware stack precisely. The orchestrator coordinates the full kill chain
by delegating to specialist sub-agents (soundwave, recon, exploit, postexploit).

Middleware stack (selected for orchestration):
  1. SafeCommandMiddleware — block session-destroying bash commands
  2. SkillsMiddleware — progressive disclosure of SKILL.md knowledge
  3. FilesystemMiddleware — file ops for reading/updating engagement docs
  4. SubAgentMiddleware — task() tool for delegating to sub-agents
  5. OPPLANMiddleware — OPPLAN CRUD tools (create/add/get/list/update objectives)
  6. ModelFallbackMiddleware — opus 4.6 → gpt-5.4 fallback on primary failure
  7. SummarizationMiddleware — auto-compact for long orchestration sessions
  8. AnthropicPromptCachingMiddleware — cache system prompt for Anthropic
  9. PatchToolCallsMiddleware — repair dangling tool calls

OPPLAN replaces TodoListMiddleware with domain-specific objective tracking:
  - 5 CRUD tools following Claude Code's V2 Task tool patterns
  - Dynamic state injection: every LLM call sees OPPLAN progress table
  - State transition validation with dependency checking

Sub-agents are passed as CompiledSubAgent, wrapping existing agent factories
(create_soundwave_agent, create_recon_agent, create_exploit_agent,
create_postexploit_agent) so they run with their full middleware stack and
skill sets intact.
"""

from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgentMiddleware
from deepagents.middleware.summarization import create_summarization_middleware
from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

from decepticon.agents.prompts import load_prompt
from decepticon.backends import DockerSandbox
from decepticon.core.config import load_config
from decepticon.core.subagent_streaming import StreamingRunnable
from decepticon.llm import LLMFactory
from decepticon.middleware import OPPLANMiddleware, SafeCommandMiddleware
from decepticon.middleware.skills import DecepticonSkillsMiddleware
from decepticon.tools.bash import bash
from decepticon.tools.bash.bash import set_sandbox

# Resolve paths relative to repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]


def create_decepticon_agent():
    """Initialize the Decepticon Orchestrator using create_agent() directly.

    Context engineering decisions:
      - Explicit middleware stack instead of create_deep_agent() defaults
      - SubAgentMiddleware: task() tool for delegating to specialist sub-agents
      - OPPLANMiddleware: 5 CRUD tools for objective tracking (Claude Code V2 Task pattern)
      - ModelFallbackMiddleware: opus 4.6 primary → gpt-5.4 fallback on failure
      - CompositeBackend: /skills/* → host FS (read-only), default → Docker sandbox

    Returns a compiled LangGraph agent ready for invocation.
    """
    config = load_config()

    factory = LLMFactory()
    llm = factory.get_model("decepticon")
    fallback_models = factory.get_fallback_models("decepticon")

    # Build DockerSandbox — shared filesystem for all agents
    sandbox = DockerSandbox(
        container_name=config.docker.sandbox_container_name,
    )
    set_sandbox(sandbox)

    system_prompt = load_prompt("decepticon", shared=["bash"])

    # Route /skills/ to host filesystem; everything else goes into the container
    backend = CompositeBackend(
        default=sandbox,
        routes={"/skills/": FilesystemBackend(root_dir=_REPO_ROOT / "skills", virtual_mode=True)},
    )

    # Build sub-agents from existing agent factories
    from decepticon.agents.exploit import create_exploit_agent
    from decepticon.agents.postexploit import create_postexploit_agent
    from decepticon.agents.recon import create_recon_agent
    from decepticon.agents.soundwave import create_soundwave_agent

    # Wrap each sub-agent with StreamingRunnable so their tool calls, results,
    # and AI messages stream through both Python CLI (UIRenderer) and
    # LangGraph Platform HTTP API (get_stream_writer → custom events).
    subagents = [
        CompiledSubAgent(
            name="soundwave",
            description=(
                "Document writer agent. Generates engagement document bundles: RoE, CONOPS, "
                "Deconfliction Plan. Use when engagement documents are missing or need updating. "
                "Interviews the user, produces JSON documents, validates against schemas. "
                "Does NOT manage OPPLAN — the orchestrator owns OPPLAN directly. "
                "Saves results to /workspace/"
            ),
            runnable=StreamingRunnable(create_soundwave_agent(), "soundwave"),
        ),
        CompiledSubAgent(
            name="recon",
            description=(
                "Reconnaissance agent. Passive/active recon, OSINT, web/cloud recon. "
                "Use for: subdomain enumeration, port scanning, service detection, "
                "vulnerability scanning, OSINT gathering. "
                "Saves results to /workspace/recon/"
            ),
            runnable=StreamingRunnable(create_recon_agent(), "recon"),
        ),
        CompiledSubAgent(
            name="exploit",
            description=(
                "Exploitation agent. Initial access via web/AD attacks. "
                "Use for: SQLi, SSTI, Kerberoasting, ADCS abuse, credential attacks. "
                "Use after recon identifies attack surface. "
                "Saves results to /workspace/exploit/"
            ),
            runnable=StreamingRunnable(create_exploit_agent(), "exploit"),
        ),
        CompiledSubAgent(
            name="postexploit",
            description=(
                "Post-exploitation agent. Credential access, privilege escalation, "
                "lateral movement, C2 management. "
                "Use after initial foothold is established. "
                "Saves results to /workspace/post-exploit/"
            ),
            runnable=StreamingRunnable(create_postexploit_agent(), "postexploit"),
        ),
    ]

    # Assemble middleware stack
    middleware = [
        SafeCommandMiddleware(),
        DecepticonSkillsMiddleware(backend=backend, sources=["/skills/decepticon/", "/skills/shared/"]),
        FilesystemMiddleware(backend=backend),
        SubAgentMiddleware(backend=backend, subagents=subagents),
        OPPLANMiddleware(),
    ]
    if fallback_models:
        middleware.append(ModelFallbackMiddleware(*fallback_models))
    middleware.extend(
        [
            create_summarization_middleware(llm, backend),
            AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
            PatchToolCallsMiddleware(),
        ]
    )

    agent = create_agent(
        llm,
        system_prompt=system_prompt,
        tools=[bash],
        middleware=middleware,
        name="decepticon",
    )

    # Orchestrator needs a higher recursion budget than sub-agents (100).
    return agent.with_config({"recursion_limit": 200})


# Module-level graph for LangGraph Platform (langgraph serve)
graph = create_decepticon_agent()
