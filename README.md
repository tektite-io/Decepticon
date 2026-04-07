[![English](https://img.shields.io/badge/Language-English-blue?style=for-the-badge)](README.md)
[![한국어](https://img.shields.io/badge/Language-한국어-red?style=for-the-badge)](./docs/README_KO.md)


<div align="center">
  <img src="assets/logo_banner.png" alt="Decepticon Logo">
</div>

<h1 align="center">Decepticon — Autonomous Hacking Agent</h1>

<p align="center"><i>"Another AI hacker? Let us guess — it runs nmap and writes a report. How original. Then what?"</i></p>

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
<a href="https://decepticon.red">
  <img src="https://img.shields.io/badge/Website-decepticon.red-brightgreen?logo=vercel&logoColor=white&style=for-the-badge" alt="Website">
</a>
<a href="https://docs.decepticon.red">
  <img src="https://img.shields.io/badge/Docs-docs.decepticon.red-8B5CF6?logo=bookstack&logoColor=white&style=for-the-badge" alt="Documentation">
</a>

</div>

<br/>

<div align="center">
  <video src="https://github.com/user-attachments/assets/b3fd40d8-e859-4a39-97f4-bd825694ad96" width="800" controls></video>
</div>

## Install

**Prerequisites**: [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2. That's it.

```bash
curl -fsSL https://decepticon.red/install | bash
```

Then configure your API key and start:

```bash
decepticon config    # Set your Anthropic or OpenAI API key
decepticon           # Launch
```

## Try the Demo

Configure your API key first, then run the demo — nothing else needed.

```bash
decepticon config    # Set your API key (one-time)
decepticon demo
```

Launches Metasploitable 2 as a target, loads a pre-built engagement, and runs the full kill chain automatically: port scan, vsftpd exploit, Sliver C2 implant deployment, credential harvesting via C2, and internal network reconnaissance.

---

> **Disclaimer** — Do not use this project on any system or network without explicit written authorization from the system owner. Unauthorized access to computer systems is illegal. You are solely responsible for your actions. The authors and contributors of this project assume no liability for misuse.

---

## What is Autonomous Hacking?

Let's be honest. The "AI + hacking" space is exhausting.

Every other week, someone drops a demo: *"Look, GPT can run nmap!"* Cool. Then what? It either ends up as a party trick that no one actually uses in production — or worse, it crosses a line nobody should cross.

> *"Yet another AI pentesting tool... cool demo. But when does it actually do something a real attacker would?"*

Fair question. Here's our answer.

**Autonomous Hacking** is the next evolution in offensive security. It's not about making hacking easier or more accessible. It's about making **real Red Team operations** executable at machine speed — with the rigor, documentation, and legal framework that separates professionals from script kiddies.

Traditional red teaming demands hundreds of hours of manual work — scanning, enumerating, pivoting, documenting — most of it repetitive, all of it exhausting. Meanwhile, the attack surface grows faster than any human team can cover.

Autonomous Hacking changes the equation. AI agents handle the grind: running scans, analyzing output, chaining techniques, and adapting in real time. The human sets the mission, defines the rules, and focuses on what machines still can't do — intuition, judgment, and creative thinking.

> *"Delegate the repetitive. Focus on the decisive."*

## "But wait — aren't you guys just the same?"

Great question. Short answer: **No.**

Here's the thing most people miss about offensive security — there's a massive difference between *hacking* and *Red Team Testing*.

Red Team Testing is a **regulated, authorized, professional discipline**. Before a single packet leaves the wire, there are documents. Agreements. Rules.

- **RoE (Rules of Engagement)** — Defines what you can and can't touch. Scope, timing, boundaries. Violate this and you're not a red teamer, you're a criminal.
- **ConOps (Concept of Operations)** — Threat actor profile, attack methodology, the "who are we pretending to be" document.
- **Deconfliction Plan** — Separates red team activity from real threats. Source IPs, user-agents, time windows, and a shared code for real-time deconfliction calls with the SOC.
- **OPPLAN (Operations Plan)** — The full mission plan. Objectives, kill chain phases, acceptance criteria. Every action maps to a purpose.

**Decepticon supports all of this. Obviously.**

Every engagement starts with proper documentation. Every objective is tracked. Every action operates within defined boundaries. The agent doesn't just hack — it operates under a formal operations plan, respects the Rules of Engagement, and produces auditable findings.

This isn't a toy. It's a professional Red Team platform that happens to be autonomous.

## Why Decepticon?

Penetration testing finds vulnerabilities. Red teaming answers a harder question: *can your organization survive a real attack?*

Most security tools stop at the scan report. Decepticon doesn't. It thinks in kill chains — reconnaissance, exploitation, privilege escalation, lateral movement, persistence — executing multi-stage operations the way a real adversary would, not the way a scanner does.

Four principles guide everything we build:

**Real Red Teaming, Not Checkbox Security**
Decepticon emulates actual adversary behavior — not just running CVE checks against a list of ports. It reads an operations plan, adapts to what it finds, and pursues objectives through whatever path opens up. The goal is to test your defenses the way they'll actually be tested.

**Interactive Shell Sessions**
Real offensive security tools are interactive — `sliver-client`, `msfconsole`, `evil-winrm`, `sqlmap`, `impacket-psexec`. They don't just take a command and exit. They drop you into a prompt, wait for input, and expect a conversation. Most AI agents can't handle this — they fire one-shot commands via `subprocess.run()` and call it a day. Decepticon runs every command inside persistent tmux sessions with automatic prompt detection. When a tool presents an interactive prompt (`sliver >`, `msf6 >`, `PS C:\>`), the agent detects it and sends follow-up commands — the same way a human operator would. Parallel named sessions, control signals (`C-c`, `C-z`), and stall detection are built in. No workarounds, no hacks. The agent actually *operates* the tools.

**Complete Isolation — Real Red Team Infrastructure**
Every command runs inside a hardened Kali Linux sandbox on a dedicated operational network (`sandbox-net`), fully isolated from the management infrastructure (`decepticon-net`). The C2 team server, victim targets, and the operator sandbox live on one network; the LLM gateway, agent API server, and database live on another. No cross-network access. LangGraph reaches the sandbox exclusively via Docker socket — not the network. You get the full offensive toolkit — nmap, Sliver C2, sqlmap, Impacket — without any risk of leaking credentials or touching the host.

**CLI-First**
Security work belongs in the terminal. Decepticon's interface is a real-time streaming CLI built with Ink — no browser tabs, no dashboards, no context switching. You see what the agent sees, as it happens.

## The Bigger Picture: Offense Serves Defense

Here's what most "offensive AI" projects get wrong: they treat the attack as the destination.

**Decepticon is not the destination. It's Step 1.**

> There are already plenty of offensive AI agents out there. The world doesn't need another "look, AI can hack things" demo.

What the world actually needs is a system that turns offensive capabilities into **defensive evolution**. That's the real vision:

1. **Step 1 — Autonomous Offensive Agent**: Build a world-class hacking agent that executes realistic Red Team operations. *We are here.*
2. **Step 2 — Infinite Offensive Feedback**: Deploy the agent to generate continuous, diverse attack scenarios — an endless stream of real-world threat simulation.
3. **Step 3 — Defensive Evolution**: Channel that feedback into Blue Team capabilities — detection rules, response playbooks, hardening strategies. The defense evolves because the offense never stops.

Think of it as an **Offensive Vaccine**. Just as a biological vaccine exposes the body to weakened pathogens to build immunity, Decepticon exposes your infrastructure to relentless AI-driven attacks to build resilience.

The true value isn't in the attack. It's in the defense system that emerges from surviving it.

## Features

### Engagement Planning

The **Soundwave** agent interviews the operator and generates a complete engagement package — RoE, ConOps, Deconfliction Plan, and OPPLAN. The OPPLAN feeds directly into the autonomous loop; the RoE is enforced every iteration.

### Autonomous Kill Chain Execution

The orchestrator iterates through OPPLAN objectives autonomously:

1. Pick next pending objective → build prompt with RoE guard rails + previous findings
2. Spawn a **fresh agent** with a clean context window → execute
3. Parse PASSED/BLOCKED signal → update status → append findings to disk → next

Fresh context per objective — no accumulated noise. Findings persist to files, not agent memory. The orchestrator tracks dependencies and state transitions, adapting the attack path in real time.

### C2 Integration

**Sliver C2 team server** runs on the operational network. The sandbox has `sliver-client` pre-installed with auto-generated operator config.

- Implant generation, deployment, and session management
- mTLS, HTTPS, and DNS-based C2 channels
- Post-exploitation via C2 sessions: credential harvesting, lateral movement, internal recon

C2 is profile-based — `COMPOSE_PROFILES=c2-sliver`. Swap the profile to change frameworks.

### Skill System

Progressive skill disclosure — only frontmatter loaded initially, full content on-demand via `read_file()`. Skills organized by kill chain phase with MITRE ATT&CK tags. Covers OSINT, web exploitation, AD attacks, privilege escalation, lateral movement, credential access, defense evasion, and OPSEC.

### MITRE ATT&CK Integration

ATT&CK mapping at every layer — not added after the fact:

- **Objectives** — each OPPLAN objective carries `mitre` technique IDs (e.g., `T1190`, `T1003.001`)
- **Skills** — ATT&CK techniques declared in frontmatter, displayed inline in agent's skill catalog
- **Threat actors** — ConOps defines `initial_access` and `ttps` as ATT&CK IDs

### Multi-Model Routing

LiteLLM proxy routes to any backend (Anthropic, OpenAI, Google). Three profiles:

| Profile | Orchestrator | Exploit | Recon | Use Case |
|---------|-------------|---------|-------|----------|
| **eco** | Opus 4.6 | Sonnet 4.6 | Haiku 4.5 | Production |
| **max** | Opus 4.6 | Opus 4.6 | Sonnet 4.6 | High-value targets |
| **test** | Haiku 4.5 | Haiku 4.5 | Haiku 4.5 | Development/CI |

Each role has automatic fallback (e.g., Opus → GPT-5.4). Provider outage or rate limit → seamless switch.

## Architecture

Two isolated networks. Management (`decepticon-net`) and operations (`sandbox-net`) share zero network access. LangGraph controls the sandbox exclusively via Docker socket.

<div align="center">
  <img src="assets/decepticon_infra.svg" alt="Decepticon Infrastructure" width="680">
</div>

## Agents

Five specialist agents, each with its own tools, skills, and clean context window: **Decepticon** (orchestrator), **Soundwave** (engagement planning), **Recon**, **Exploit**, and **Post-Exploit**. Each agent spawns fresh per objective — no accumulated noise, no degraded reasoning.

**[Agent details and middleware stack →](docs/agents.md)**

## CLI

```bash
decepticon           # Start all services and open the interactive CLI
decepticon demo      # Run guided demo (full kill chain + Sliver C2)
decepticon config    # Edit API keys and settings
decepticon stop      # Stop all services
```

**[Full CLI reference →](docs/cli.md)**

## Vision & Philosophy

This README covers the essentials — but there's a deeper story behind why Decepticon exists, where it's headed, and the philosophy that drives every design decision.

**[Read the full vision and philosophy at docs.decepticon.red](https://docs.decepticon.red)**

Topics covered in the documentation:
- **Core Philosophy** — Reasoning over signatures, hybrid intelligence, stealth as foundation
- **Pentesting vs. Red Teaming** — Why the distinction matters and where Decepticon sits
- **History & Evolution** — From Purple Team AI (2021) through RL and GANs to today's autonomous agents
- **Target Architecture** — Multi-agent hybrid architecture, C2-based stealth execution
- **Why Open Source** — Collective intelligence and the Red/Blue Team feedback loop

## Contributing

We welcome contributions. Whether you're a security researcher, an AI engineer, or someone who cares about making defense better — there's a place for you here.

**Developer Setup** (for contributors):

```bash
git clone https://github.com/PurpleAILAB/Decepticon.git
cd Decepticon

# Start with hot-reload (builds Docker images + watches for source changes)
make dev

# In a separate terminal — open the interactive CLI
make cli
```

Development runs in the **same Docker containers** as production. Source changes are automatically synced into containers via `docker compose watch` — no manual rebuilds needed.

```bash
make dev          # Build + start with hot-reload
make cli          # Interactive CLI (separate terminal)
make start        # Start in background (no hot-reload, production-like)
make stop         # Stop all services
make test         # Run pytest inside container
make lint         # Lint + typecheck locally (requires: uv sync --dev)
make help         # Show all available targets
```

1. Fork the repository
2. Create a feature branch
3. Commit with clear messages
4. Open a Pull Request

For architecture details and contribution guidelines, visit the [documentation](https://docs.decepticon.red).

## Community

Join the [Discord](https://discord.gg/TZUYsZgrRG) — ask questions, share engagement logs, discuss techniques, or just connect with others who believe defense starts with understanding offense.

## License

[Apache-2.0](LICENSE)

---

<div align="center">
  <img src="assets/main.png" alt="Decepticon">
</div>
