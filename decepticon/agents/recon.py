"""Recon Agent — autonomous reconnaissance and intelligence gathering.

Uses create_agent() directly (not create_deep_agent()) to control the
middleware stack precisely.

Middleware stack (selected for recon):
  1. SkillsMiddleware — progressive disclosure of SKILL.md knowledge
  2. FilesystemMiddleware — ls/read/write/edit/glob/grep/execute tools
  3. ModelFallbackMiddleware — haiku 4.5 → gemini 2.5 flash fallback on primary failure
  4. SummarizationMiddleware — auto-compact when context budget exceeded
  5. AnthropicPromptCachingMiddleware — cache system prompt for Anthropic
  6. PatchToolCallsMiddleware — repair dangling tool calls

Backend routing (CompositeBackend):
  /skills/*                → FilesystemBackend (host FS, read-only SKILL.md access)
  /workspace/.decepticon/* → FilesystemBackend (host FS, client-visible reports)
  default                  → DockerSandbox     (all file ops + bash execution in container)
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
from decepticon.tools.bash import bash
from decepticon.tools.bash.tool import set_sandbox

# Resolve paths relative to repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_FILE = Path(__file__).parent / "prompts" / "recon.md"


def _load_system_prompt() -> str:
    """Load the recon agent system prompt from the external markdown file."""
    return PROMPT_FILE.read_text(encoding="utf-8")


def create_recon_agent():
    """Initialize the Recon Agent using langchain create_agent() directly.

    Context engineering decisions:
      - CompositeBackend: /skills/* → host FS (read-only), default → Docker sandbox
      - /workspace/.decepticon/ → host FS (always <project_root>/.decepticon/)
      - InMemoryStore: cross-thread memory for persisting findings across sessions
      - ModelFallbackMiddleware: haiku 4.5 primary → gemini 2.5 flash fallback on failure
      - No TodoListMiddleware: opplan.json handles task tracking
      - No SubAgentMiddleware: Decepticon orchestrator handles agent delegation
    """
    config = load_config()

    factory = LLMFactory()
    llm = factory.get_model("recon")
    fallback_models = factory.get_fallback_models("recon")

    # Build DockerSandbox and inject into bash tool
    sandbox = DockerSandbox(
        container_name=config.docker.sandbox_container_name,
    )
    set_sandbox(sandbox)

    system_prompt = _load_system_prompt()

    checkpointer = MemorySaver()
    store = InMemoryStore()

    # Route /skills/ to host filesystem; everything else goes into the container.
    report_dir = _REPO_ROOT / ".decepticon"
    report_dir.mkdir(parents=True, exist_ok=True)

    routes: dict[str, FilesystemBackend] = {
        "/skills/": FilesystemBackend(root_dir=_REPO_ROOT / "skills", virtual_mode=True),
        "/workspace/.decepticon/": FilesystemBackend(root_dir=report_dir),
    }

    backend = CompositeBackend(default=sandbox, routes=routes)

    # Assemble middleware stack
    middleware = [
        SkillsMiddleware(backend=backend, sources=["/skills/recon/", "/skills/shared/"]),
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
        tools=[bash],
        middleware=middleware,
        checkpointer=checkpointer,
        store=store,
        name="recon",
    ).with_config({"recursion_limit": 40})

    return agent
