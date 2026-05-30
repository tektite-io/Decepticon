# MCP tool servers (opt-in)

Decepticon can attach to external **Model Context Protocol** (MCP)
servers — e.g. a Kali MCP daemon or HexStrike — and expose their
tools to the agents alongside the built-in ones.

The integration is **opt-in** and **additive**: nothing is loaded
unless you both (a) install the optional adapter package and (b)
point Decepticon at one or more MCP servers via an env var.

## 1. Install the adapter

```bash
pip install langchain-mcp-adapters
```

The dependency is intentionally **not** in `decepticon`'s base
install — operators who don't use MCP don't pay for it. If the
package is missing when MCP is configured, Decepticon logs a single
warning and continues with built-in tools only.

## 2. Declare your servers

Set `DECEPTICON_MCP__SERVERS` to a JSON object mapping a server name
to a per-server config:

```bash
export DECEPTICON_MCP__SERVERS='{
  "kali": {"url": "http://localhost:8000/mcp", "transport": "streamable_http"},
  "hex":  {"command": "uvx", "args": ["hexstrike"], "transport": "stdio"}
}'
```

Per-server fields:

| Field       | Required for             | Notes                                   |
|-------------|--------------------------|-----------------------------------------|
| `transport` | always (default inferred) | `streamable_http`, `sse`, or `stdio`   |
| `url`       | HTTP transports          | server endpoint                         |
| `command`   | `stdio`                  | executable to launch                    |
| `args`      | `stdio` (optional)       | list of CLI args                        |
| `headers`   | HTTP (optional)          | extra headers, e.g. `Authorization`     |

Malformed JSON, unknown transports, or unreachable servers are
**logged and skipped** — they never crash the agent process.

## 3. Programmatic use

```python
from decepticon.tools.mcp import load_mcp_tools, mcp_servers_configured

if mcp_servers_configured():
    tools = await load_mcp_tools()
```

Auto-wiring these tools into the live agent graphs is a planned
follow-up; for now the loader is the seam.
