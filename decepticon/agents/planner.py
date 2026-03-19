"""Planner Agent — generates engagement document bundles.

Creates the complete document set (RoE, CONOPS, OPPLAN, Deconfliction Plan)
that drives the red team execution. All documents are written into a shared
Docker sandbox so that downstream agents (recon, exploit, etc.) can read them.

Uses create_agent() directly (not create_deep_agent()) to control the
middleware stack precisely.

Middleware stack (selected for planner):
  1. SkillsMiddleware — progressive disclosure of planning SKILL.md
  2. FilesystemMiddleware — ls/read/write/edit/glob/grep tools
  3. ModelFallbackMiddleware — opus 4.6 → gpt-5.4 fallback on primary failure
  4. SummarizationMiddleware — auto-compact when context budget exceeded
  5. AnthropicPromptCachingMiddleware — cache system prompt for Anthropic
  6. PatchToolCallsMiddleware — repair dangling tool calls

Backend routing (CompositeBackend):
  /skills/* → FilesystemBackend (host FS, read-only SKILL.md + references access)
  default   → DockerSandbox    (shared filesystem across agents)
"""

from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.skills import SkillsMiddleware
from deepagents.middleware.summarization import create_summarization_middleware
from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from decepticon.backends import DockerSandbox
from decepticon.core.config import load_config
from decepticon.llm import LLMFactory

# Resolve paths relative to repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_FILE = Path(__file__).parent / "prompts" / "planning.md"


def _load_system_prompt() -> str:
    """Load the planner agent system prompt from the external markdown file."""
    return PROMPT_FILE.read_text(encoding="utf-8")


def create_planner_agent():
    """Initialize the Planner Agent using langchain create_agent() directly.

    Context engineering decisions:
      - No TodoListMiddleware: opplan objectives handle task tracking
      - No SubAgentMiddleware: planner is standalone
      - No bash tool: planner is document-generation only
      - ModelFallbackMiddleware: opus 4.6 primary → gpt-5.4 fallback on failure
    """
    config = load_config()

    factory = LLMFactory()
    llm = factory.get_model("planning")
    fallback_models = factory.get_fallback_models("planning")

    # DockerSandbox as shared filesystem — other agents read planner output here
    sandbox = DockerSandbox(
        container_name=config.docker.sandbox_container_name,
    )

    system_prompt = _load_system_prompt()

    checkpointer = MemorySaver()
    store = InMemoryStore()

    # Route /skills/ to host filesystem; everything else goes into the container
    backend = CompositeBackend(
        default=sandbox,
        routes={"/skills/": FilesystemBackend(root_dir=_REPO_ROOT / "skills", virtual_mode=True)},
    )

    # Assemble middleware stack
    middleware = [
        SkillsMiddleware(backend=backend, sources=["/skills/planning/"]),
        FilesystemMiddleware(backend=backend),
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
        tools=[],
        middleware=middleware,
        checkpointer=checkpointer,
        store=store,
        name="planner",
    ).with_config({"recursion_limit": 40})

    return agent
