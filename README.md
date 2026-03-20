<div align="center">
  <img src="assets/logo_banner.png" alt="Decepticon" width="600">
</div>

<p align="center">Vibe Hacking Agent</p>

<div align="center">

<a href="https://github.com/PurpleAILAB/Decepticon/blob/main/LICENSE">
  <img src="https://img.shields.io/github/license/PurpleAILAB/Decepticon?style=for-the-badge&color=blue" alt="License: Apache 2.0">
</a>
<a href="https://github.com/PurpleAILAB/Decepticon/stargazers">
  <img src="https://img.shields.io/github/stars/PurpleAILAB/Decepticon?style=for-the-badge&color=yellow" alt="Stargazers">
</a>
<a href="https://discord.gg/TZUYsZgrRG">
  <img src="https://img.shields.io/badge/Discord-Join%20Us-7289DA?logo=discord&logoColor=white&style=for-the-badge" alt="Join us on Discord">
</a>
<a href="https://purpleailab.mintlify.app">
  <img src="https://img.shields.io/badge/Docs-purpleailab.mintlify.app-8B5CF6?logo=bookstack&logoColor=white&style=for-the-badge" alt="Documentation">
</a>

</div>

---

> **Warning**: Do not use this project on any system or network without explicit authorization.

> Decepticon 2.0 is under active development. For architecture, philosophy, and full documentation visit **[purpleailab.mintlify.app](https://purpleailab.mintlify.app)**.

<div align="center">
  <img src="assets/cli.png" alt="Decepticon CLI" width="800">
</div>

---

## Quick Start

### Prerequisites

- Python 3.13+
- Node.js 20+
- [uv](https://docs.astral.sh/uv/)
- Docker & Docker Compose

### 1. Clone & Install

```bash
git clone -b refactor https://github.com/PurpleAILAB/Decepticon.git
cd Decepticon

# Python (agents + LangGraph server)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# CLI client
cd clients/cli && npm install && cd ../..
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY and/or OPENAI_API_KEY
```

### 3. Start Services

```bash
# Core: LiteLLM proxy + PostgreSQL + Kali sandbox + LangGraph server
docker compose up -d --build

# (Optional) Demo targets for testing
docker compose --profile victims up -d
```

### 4. Run CLI

```bash
cd clients/cli
npm run dev
```

## License

[Apache-2.0](LICENSE)
