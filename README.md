[![English](https://img.shields.io/badge/Language-English-blue?style=for-the-badge)](README.md)
[![한국어](https://img.shields.io/badge/Language-한국어-red?style=for-the-badge)](./docs/README_KO.md)


<div align="center">
  <img src="assets/logo_banner.png" alt="Decepticon Logo">
</div>

<h1 align="center">Decepticon — Vibe Hacking Agent</h1>

<div align="center">

<a href="https://github.com/PurpleAILAB/Decepticon/blob/main/LICENSE">
  <img src="https://img.shields.io/github/license/PurpleAILAB/Decepticon?style=for-the-badge&color=blue" alt="License: Apache 2.0">
</a>
<a href="https://github.com/PurpleAILAB/Decepticon/stargazers">
  <img src="https://img.shields.io/github/stars/PurpleAILAB/Decepticon?style=for-the-badge&color=yellow" alt="Stargazers">
</a>
<a href="https://github.com/PurpleAILAB/Decepticon/graphs/contributors">
  <img src="https://img.shields.io/github/contributors/PurpleAILAB/Decepticon?style=for-the-badge&color=orange" alt="Contributors">
</a>

<br/>

<a href="https://discord.gg/TZUYsZgrRG">
  <img src="https://img.shields.io/badge/Discord-Join%20Us-7289DA?logo=discord&logoColor=white&style=for-the-badge" alt="Join us on Discord">
</a>
<a href="https://purplelab.framer.ai">
  <img src="https://img.shields.io/badge/Website-purplelab.framer.ai-brightgreen?logo=vercel&logoColor=white&style=for-the-badge" alt="Website">
</a>
<a href="https://purpleailab.mintlify.app">
  <img src="https://img.shields.io/badge/Docs-purpleailab.mintlify.app-8B5CF6?logo=bookstack&logoColor=white&style=for-the-badge" alt="Documentation">
</a>

</div>

<br/>

<div align="center">
  <img src="assets/cli.png" alt="Decepticon CLI" width="800">
</div>

## Install

**Prerequisites**: [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2. That's it.

```bash
curl -fsSL https://raw.githubusercontent.com/PurpleAILAB/Decepticon/main/scripts/install.sh | bash
```

Then configure your API key and start:

```bash
decepticon config    # Set your Anthropic or OpenAI API key
decepticon           # Launch
```

## Try the Demo

No configuration needed — just Docker and an API key.

```bash
decepticon demo
```

Launches Metasploitable 2 as a target, loads a pre-built engagement, and runs the full kill chain automatically: port scan, service enumeration, vsftpd exploit, and post-exploitation.

---

> **Disclaimer** — Do not use this project on any system or network without explicit written authorization from the system owner. Unauthorized access to computer systems is illegal. You are solely responsible for your actions. The authors and contributors of this project assume no liability for misuse.

---

## What is Vibe Hacking?

**Vibe Hacking** is a new paradigm in offensive security, defined by PurpleAILAB.

Traditional red teaming demands hundreds of hours of manual work — scanning, enumerating, pivoting, documenting — most of it repetitive, all of it exhausting. Meanwhile, the attack surface grows faster than any team can cover.

Vibe Hacking changes the equation. Instead of replacing the operator, AI agents handle the grind: running scans, analyzing output, chaining techniques, and adapting in real time. The human sets the mission, defines the rules, and focuses on what machines still can't do — intuition, judgment, and creative thinking.

> *"Delegate the repetitive. Focus on the decisive."*

This isn't about making hacking easier. It's about making red teams **fast enough to matter** — before the next breach proves they weren't.

## Why Decepticon?

Penetration testing finds vulnerabilities. Red teaming answers a harder question: *can your organization survive a real attack?*

Most security tools stop at the scan report. Decepticon doesn't. It thinks in kill chains — reconnaissance, exploitation, privilege escalation, lateral movement, persistence — executing multi-stage operations the way a real adversary would, not the way a scanner does.

Three principles guide everything we build:

**Real Red Teaming, Not Checkbox Security**
Decepticon emulates actual adversary behavior — not just running CVE checks against a list of ports. It reads an operations plan, adapts to what it finds, and pursues objectives through whatever path opens up. The goal is to test your defenses the way they'll actually be tested.

**Complete Isolation**
Every command runs inside a hardened Kali Linux sandbox. No tools touch the host. No credentials leak. No accidental blast radius. You get the full offensive toolkit — nmap, metasploit, custom scripts — without the risk of running them on your own machine.

**CLI-First**
Security work belongs in the terminal. Decepticon's interface is a real-time streaming CLI built with Ink — no browser tabs, no dashboards, no context switching. You see what the agent sees, as it happens.

## Agents

Decepticon runs a **multi-agent system** where a central orchestrator delegates to specialist agents, each with its own tools, skills, and context window.

| Agent | Role |
|-------|------|
| **Decepticon** | Orchestrator. Reads the operations plan, coordinates the kill chain, delegates tasks to specialists. |
| **Recon** | Reconnaissance and enumeration. Runs scans, discovers services, maps attack surface inside the sandbox. |
| **Planner** | Document generation. Produces ConOps, operations plans, and rules of engagement from mission briefs. |
| **Exploit** | Exploitation. Attempts access through discovered vulnerabilities, credentials, or misconfigurations. |
| **Post-Exploit** | Post-exploitation. Privilege escalation, lateral movement, persistence, and data collection. |

Each agent spawns with a **clean context window** per objective — no accumulated noise, no degraded reasoning. Findings persist to disk, not to memory, so every iteration starts sharp.

## CLI Commands

| Command | Description |
|---------|-------------|
| `decepticon` | Start all services and open the interactive CLI |
| `decepticon demo` | Run guided demo against Metasploitable 2 |
| `decepticon stop` | Stop all services |
| `decepticon update [-f]` | Pull latest images and sync configuration (`--force` to re-pull same version) |
| `decepticon status` | Show service status |
| `decepticon logs [service]` | Follow service logs (default: langgraph) |
| `decepticon config` | Edit API keys and settings |
| `decepticon victims` | Start vulnerable test targets (DVWA, Metasploitable) |
| `decepticon remove` | Uninstall Decepticon completely |
| `decepticon --version` | Show installed version |

## Contributing

We welcome contributions. Whether you're a security researcher, an AI engineer, or someone who cares about making defense better — there's a place for you here.

**Developer Setup** (for contributors):

```bash
git clone https://github.com/PurpleAILAB/Decepticon.git
cd Decepticon

# Python agents
uv sync --dev

# CLI client
cd clients/cli && npm install && cd ../..

# Run locally
docker compose up -d --build
cd clients/cli && npm run dev
```

1. Fork the repository
2. Create a feature branch
3. Commit with clear messages
4. Open a Pull Request

For architecture details and contribution guidelines, visit the [documentation](https://purpleailab.mintlify.app).

## Community

Join the [Discord](https://discord.gg/TZUYsZgrRG) — ask questions, share engagement logs, discuss techniques, or just connect with others who believe defense starts with understanding offense.

## License

[Apache-2.0](LICENSE)

---

<div align="center">
  <img src="assets/main.png" alt="Decepticon">
</div>
