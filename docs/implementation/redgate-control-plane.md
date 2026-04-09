# RedGate Control Plane — Implementation Guide

> Decepticon의 레드팀 제어 평면. OpenClaw Gateway 패턴을 Python으로 구현.

## 1. Tech Stack Decision

### 1.1 선정 기준

| 기준 | 선택 | 근거 |
|------|------|------|
| **Language** | Python 3.13+ | Decepticon 기존 코드베이스, LangGraph/LangChain 호환 |
| **WS Server** | FastAPI + `websockets` | asyncio 네이티브, JSON 검증 내장, HTTP+WS 동일 포트 |
| **JSON-RPC** | Custom (Pydantic models) | OpenClaw 프로토콜과 동일한 req/res/event 패턴 |
| **Auth** | JWT + shared-secret | 디바이스 토큰 + API 키 이중 지원 |
| **Config** | Pydantic BaseSettings + watchdog | 현재 DecepticonConfig 확장, 파일 워치 hot-reload |
| **Discord** | discord.py 2.x | Python 네이티브, asyncio 호환, 성숙한 라이브러리 |
| **Queue** | asyncio.Queue + Semaphore | OpenClaw lane 패턴, 외부 의존성 없음 |
| **State** | SQLite + JSON files | 경량, 서버리스, red-run 검증된 패턴 |
| **Daemon** | systemd (Linux) | 현재 Docker 기반에 추가 |

### 1.2 의존성 목록

```toml
# pyproject.toml 추가 의존성
[project.optional-dependencies]
gateway = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "websockets>=14.0",
    "discord.py>=2.5",
    "watchdog>=6.0",          # config file watch
    "pyjwt>=2.10",            # JWT auth
    "aiosqlite>=0.21",        # async SQLite
    "apscheduler>=4.0",       # cron scheduling
]
```

### 1.3 기존 Decepticon 의존성과의 관계

```
현재 Decepticon stack:
  ├── langchain / langgraph      → 유지 (에이전트 런타임)
  ├── litellm                     → 유지 (LLM 라우팅)
  ├── pydantic                    → 유지 + 확장 (프로토콜 스키마)
  ├── docker (Python SDK)         → 유지 (sandbox 관리)
  └── neo4j (driver)              → 유지 (KG)

추가 (RedGate):
  ├── fastapi + uvicorn           → WS + HTTP 서버
  ├── discord.py                  → Discord 채널
  ├── watchdog                    → config hot-reload
  ├── apscheduler                 → cron 스케줄링
  └── pyjwt                       → 디바이스 인증
```

## 2. WebSocket Server

### 2.1 아키텍처

```python
# decepticon/gateway/server.py

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Decepticon RedGate")

class RedGate:
    """메인 제어 평면. OpenClaw Gateway에 대응."""
    
    def __init__(self, config: RedGateConfig):
        self.config = config
        self.connections: dict[str, WebSocket] = {}   # connId → ws
        self.router = EngagementRouter(config)
        self.session_mgr = SessionManager(config)
        self.agent_pool = AgentPool(config)
        self.hook_engine = OPSECHookEngine(config)
        self.scheduler = ScanScheduler(config)
        self.notifier = DiscordNotifier(config)
        self.auth = AuthResolver(config)
    
    async def start(self):
        """서버 시작."""
        # 1. Config 로드
        await self.config.load()
        
        # 2. Discord 봇 시작
        await self.notifier.start()
        
        # 3. Cron 스케줄러 시작
        await self.scheduler.start()
        
        # 4. Config file watch 시작
        self.config_watcher = ConfigWatcher(
            self.config.path,
            on_change=self._on_config_change,
        )
        
        # 5. HTTP + WS 서버 시작
        config = uvicorn.Config(
            app, host=self.config.bind, port=self.config.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()
```

### 2.2 WebSocket 핸들러

```python
# decepticon/gateway/ws_handler.py

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """OpenClaw WS 프로토콜 구현."""
    await websocket.accept()
    conn_id = str(uuid4())
    
    try:
        # Phase 1: Connect 핸드셰이크 (첫 프레임 MUST be connect)
        raw = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=60.0,  # PREAUTH_HANDSHAKE_TIMEOUT
        )
        frame = RequestFrame.model_validate(raw)
        
        if frame.method != "connect":
            await websocket.send_json({
                "type": "res", "id": frame.id, "ok": False,
                "error": {"code": "INVALID_REQUEST", "message": "First frame must be connect"}
            })
            await websocket.close()
            return
        
        # Phase 2: Auth 검증
        auth_result = await gate.auth.verify(frame.params)
        if not auth_result.ok:
            await websocket.send_json({
                "type": "res", "id": frame.id, "ok": False,
                "error": {"code": "AUTH_FAILED", "message": auth_result.reason}
            })
            await websocket.close()
            return
        
        # Phase 3: Hello-OK 응답
        gate.connections[conn_id] = websocket
        await websocket.send_json({
            "type": "res", "id": frame.id, "ok": True,
            "payload": {
                "type": "hello-ok",
                "protocol": 1,
                "server": {"version": __version__, "connId": conn_id},
                "features": {
                    "methods": ["engagement.start", "objective.assign", 
                                "agent.spawn", "agent.status", "scan.schedule"],
                    "events": ["objective", "finding", "defense", "opsec", "tick"],
                },
                "snapshot": await gate.get_snapshot(),
            }
        })
        
        # Phase 4: 메시지 루프
        async for raw in websocket.iter_json():
            frame = RequestFrame.model_validate(raw)
            response = await gate.handle_rpc(conn_id, frame)
            await websocket.send_json(response.model_dump())
    
    except WebSocketDisconnect:
        pass
    finally:
        gate.connections.pop(conn_id, None)
```

### 2.3 JSON-RPC 프로토콜

```python
# decepticon/gateway/protocol.py

from pydantic import BaseModel, Field
from typing import Literal, Any

class RequestFrame(BaseModel):
    """클라이언트 → 서버 요청."""
    type: Literal["req"] = "req"
    id: str = Field(description="Idempotency key (UUID)")
    method: str
    params: dict[str, Any] = {}

class ResponseFrame(BaseModel):
    """서버 → 클라이언트 응답."""
    type: Literal["res"] = "res"
    id: str
    ok: bool
    payload: dict[str, Any] | None = None
    error: ErrorPayload | None = None

class EventFrame(BaseModel):
    """서버 → 클라이언트 이벤트 (push)."""
    type: Literal["event"] = "event"
    event: str  # "objective", "finding", "defense", "opsec", "tick"
    payload: dict[str, Any] = {}
    seq: int = 0

class ErrorPayload(BaseModel):
    code: str        # "AUTH_FAILED", "INVALID_REQUEST", "ROE_VIOLATION", etc.
    message: str
    retryable: bool = False
```

### 2.4 RPC 메서드 정의

```python
# decepticon/gateway/rpc_methods.py

class RPCHandler:
    """RPC 메서드 라우터. OpenClaw server-chat.ts에 대응."""
    
    async def handle(self, conn_id: str, frame: RequestFrame) -> ResponseFrame:
        handler = getattr(self, f"_handle_{frame.method.replace('.', '_')}", None)
        if not handler:
            return ResponseFrame(
                id=frame.id, ok=False,
                error=ErrorPayload(code="UNKNOWN_METHOD", message=f"Unknown: {frame.method}")
            )
        return await handler(conn_id, frame)
    
    # === Engagement 관리 ===
    async def _handle_engagement_start(self, conn_id, frame):
        """인게이지먼트 시작. RoE + OPPLAN 로드."""
        ...
    
    async def _handle_engagement_status(self, conn_id, frame):
        """인게이지먼트 상태 조회."""
        ...
    
    # === 목표 관리 ===
    async def _handle_objective_assign(self, conn_id, frame):
        """목표를 에이전트에 할당 (비동기, runId 반환)."""
        ...
    
    async def _handle_objective_status(self, conn_id, frame):
        """목표 실행 상태 조회."""
        ...
    
    # === 에이전트 관리 ===
    async def _handle_agent_spawn(self, conn_id, frame):
        """에이전트 수동 스폰."""
        ...
    
    async def _handle_agent_steer(self, conn_id, frame):
        """실행 중 에이전트에 메시지 주입."""
        ...
    
    async def _handle_agent_kill(self, conn_id, frame):
        """에이전트 종료."""
        ...
    
    # === 스캔 스케줄링 ===
    async def _handle_scan_schedule(self, conn_id, frame):
        """Cron 스캔 예약."""
        ...
    
    # === 방어 ===
    async def _handle_defense_approve(self, conn_id, frame):
        """방어 액션 승인 (Discord에서 호출)."""
        ...
    
    async def _handle_defense_rollback(self, conn_id, frame):
        """방어 액션 롤백."""
        ...
    
    # === 보고서 ===
    async def _handle_report_generate(self, conn_id, frame):
        """보고서 생성 (HackerOne/Bugcrowd/Executive)."""
        ...
```

## 3. Auth System

### 3.1 인증 모델

```python
# decepticon/gateway/auth.py

from enum import StrEnum
from pydantic import BaseModel
import jwt

class AuthMode(StrEnum):
    SHARED_SECRET = "shared-secret"   # 토큰/비밀번호
    DEVICE_TOKEN = "device-token"     # JWT 디바이스 토큰
    NONE = "none"                     # 개발 전용

class AuthResult(BaseModel):
    ok: bool
    user_id: str | None = None
    role: str = "operator"        # operator / viewer / admin
    reason: str | None = None

class AuthResolver:
    """OpenClaw auth.ts에 대응. 다중 인증 방식 지원."""
    
    def __init__(self, config: RedGateConfig):
        self.config = config
        self.jwt_secret = config.auth.jwt_secret
        self.shared_token = config.auth.token
    
    async def verify(self, params: dict) -> AuthResult:
        auth = params.get("auth", {})
        
        # 1. Shared secret (가장 간단)
        if token := auth.get("token"):
            if token == self.shared_token:
                return AuthResult(ok=True, user_id="operator", role="admin")
            return AuthResult(ok=False, reason="Invalid token")
        
        # 2. Device token (JWT)
        if device_token := auth.get("deviceToken"):
            try:
                payload = jwt.decode(device_token, self.jwt_secret, algorithms=["HS256"])
                return AuthResult(
                    ok=True,
                    user_id=payload["sub"],
                    role=payload.get("role", "operator"),
                )
            except jwt.InvalidTokenError as e:
                return AuthResult(ok=False, reason=f"Invalid device token: {e}")
        
        # 3. Discord bot (내부 연결)
        if auth.get("internal") == "discord-bot":
            return AuthResult(ok=True, user_id="discord-bot", role="operator")
        
        # 4. No auth (개발 모드)
        if self.config.auth.mode == AuthMode.NONE:
            return AuthResult(ok=True, user_id="anonymous", role="operator")
        
        return AuthResult(ok=False, reason="No credentials provided")
```

### 3.2 Discord Operator 인증

```python
# decepticon/gateway/discord_auth.py

class DiscordOperatorAuth:
    """Discord 사용자를 Decepticon 운영자로 매핑."""
    
    def __init__(self, config: RedGateConfig):
        # allowlist: Discord 사용자 ID → 역할
        self.operator_map: dict[str, str] = config.discord.operators
        # 예: {"123456789": "admin", "987654321": "operator"}
    
    def is_authorized(self, discord_user_id: str, action: str) -> bool:
        role = self.operator_map.get(discord_user_id)
        if role is None:
            return False
        
        match action:
            case "view":
                return role in ("viewer", "operator", "admin")
            case "operate":
                return role in ("operator", "admin")
            case "admin":
                return role == "admin"
            case "approve_defense":
                return role in ("operator", "admin")
        return False
```

## 4. Config System

### 4.1 설정 구조

```python
# decepticon/gateway/config.py

from pydantic_settings import BaseSettings

class RedGateConfig(BaseSettings):
    """RedGate 설정. 기존 DecepticonConfig 확장."""
    
    model_config = {"env_prefix": "DECEPTICON_"}
    
    # === Gateway ===
    bind: str = "127.0.0.1"
    port: int = 18789
    
    # === Auth ===
    auth: AuthConfig = AuthConfig()
    
    # === Discord ===
    discord: DiscordConfig = DiscordConfig()
    
    # === Scheduling ===
    scheduler: SchedulerConfig = SchedulerConfig()
    
    # === Agent Pool ===
    agent_pool: AgentPoolConfig = AgentPoolConfig()
    
    # === OPSEC ===
    opsec: OPSECConfig = OPSECConfig()
    
    # === 기존 Decepticon 설정 ===
    model_profile: ModelProfile = ModelProfile.ECO
    llm: LLMConfig = LLMConfig()
    docker: DockerConfig = DockerConfig()

class AuthConfig(BaseModel):
    mode: AuthMode = AuthMode.SHARED_SECRET
    token: str | None = None         # DECEPTICON_AUTH_TOKEN env
    jwt_secret: str | None = None    # DECEPTICON_JWT_SECRET env

class DiscordConfig(BaseModel):
    enabled: bool = False
    bot_token: str | None = None     # DECEPTICON_DISCORD_BOT_TOKEN env
    guild_id: str | None = None
    operators: dict[str, str] = {}   # user_id → role
    channels: DiscordChannels = DiscordChannels()

class DiscordChannels(BaseModel):
    control: str | None = None       # #engagement-control
    attack_log: str | None = None    # #attack-log
    defense_log: str | None = None   # #defense-log
    alerts: str | None = None        # #alerts
    approvals: str | None = None     # #approvals
    reports: str | None = None       # #reports

class SchedulerConfig(BaseModel):
    enabled: bool = True
    timezone: str = "Asia/Seoul"
    night_window_start: str = "22:00"
    night_window_end: str = "06:00"

class AgentPoolConfig(BaseModel):
    max_concurrent_sandboxes: int = 4
    max_concurrent_agents: int = 8
    sandbox_timeout: int = 3600      # 1시간
    agent_timeout: int = 172800      # 48시간 (OpenClaw 기본값)
```

### 4.2 Config Hot-Reload

```python
# decepticon/gateway/config_watcher.py

from watchdog.observers import Observer
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
import asyncio

class ConfigWatcher:
    """OpenClaw config-reload.ts에 대응. watchdog 기반 파일 감시."""
    
    def __init__(self, config_path: str, on_change: Callable, debounce_ms: int = 300):
        self.config_path = config_path
        self.on_change = on_change
        self.debounce_ms = debounce_ms
        self._debounce_task: asyncio.Task | None = None
    
    def start(self):
        handler = _ConfigFileHandler(self._on_file_change)
        self.observer = Observer()
        self.observer.schedule(handler, path=str(Path(self.config_path).parent))
        self.observer.start()
    
    def _on_file_change(self):
        """디바운스된 변경 처리."""
        if self._debounce_task:
            self._debounce_task.cancel()
        
        loop = asyncio.get_event_loop()
        self._debounce_task = loop.create_task(self._debounced_reload())
    
    async def _debounced_reload(self):
        await asyncio.sleep(self.debounce_ms / 1000)
        
        try:
            new_config = RedGateConfig.from_file(self.config_path)
            changed = self._diff_config(self.current_config, new_config)
            
            if changed:
                log.info(f"Config changed: {changed}")
                await self.on_change(new_config, changed)
        except Exception as e:
            log.error(f"Config reload failed: {e}")
    
    def _diff_config(self, old: RedGateConfig, new: RedGateConfig) -> list[str]:
        """변경된 설정 키 목록 반환."""
        changed = []
        for field in RedGateConfig.model_fields:
            if getattr(old, field) != getattr(new, field):
                changed.append(field)
        return changed
```

## 5. Discord Integration

### 5.1 Discord 봇 구현

```python
# decepticon/channels/discord_bot.py

import discord
from discord import app_commands

class DecepticonBot(discord.Client):
    """Decepticon Discord 봇. OpenClaw extensions/discord 패턴 참조."""
    
    def __init__(self, gate: RedGate):
        intents = discord.Intents.default()
        intents.message_content = True  # MESSAGE CONTENT INTENT 필수
        super().__init__(intents=intents)
        
        self.gate = gate
        self.tree = app_commands.CommandTree(self)
    
    async def on_ready(self):
        log.info(f"Discord bot ready: {self.user}")
        await self.tree.sync()
    
    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return
        
        # 1. 운영자 인증
        if not self.gate.discord_auth.is_authorized(
            str(message.author.id), "operate"
        ):
            return  # 비인증 사용자 무시
        
        # 2. 채널별 라우팅
        channel_id = str(message.channel.id)
        channel_config = self.gate.config.discord.channels
        
        if channel_id == channel_config.control:
            await self._handle_control(message)
        elif channel_id == channel_config.approvals:
            await self._handle_approval(message)
        elif message.channel.type == discord.ChannelType.public_thread:
            await self._handle_thread(message)
        else:
            # 일반 채널: 멘션 시에만 반응
            if self.user.mentioned_in(message):
                await self._handle_command(message)
    
    async def _handle_command(self, message: discord.Message):
        """멘션된 명령어 처리. OpenClaw inbound-worker 패턴."""
        content = message.content.replace(f"<@{self.user.id}>", "").strip()
        
        # 스레드 생성 (각 작업 = 독립 세션)
        thread = await message.create_thread(
            name=f"decepticon-{content[:30]}",
            auto_archive_duration=1440,  # 24시간
        )
        
        # RedGate RPC로 전달
        result = await self.gate.handle_discord_command(
            user_id=str(message.author.id),
            command=content,
            thread_id=str(thread.id),
            guild_id=str(message.guild.id) if message.guild else None,
        )
        
        await thread.send(f"Accepted. Working on: `{content[:100]}`")
    
    async def _handle_approval(self, message: discord.Message):
        """방어 액션 승인 처리."""
        content = message.content.lower().strip()
        
        if content.startswith("approve "):
            defense_id = content.split(" ")[1]
            await self.gate.approve_defense(defense_id, str(message.author.id))
            await message.add_reaction("✅")
        elif content.startswith("reject "):
            defense_id = content.split(" ")[1]
            await self.gate.reject_defense(defense_id, str(message.author.id))
            await message.add_reaction("❌")
```

### 5.2 Discord 이벤트 스트리밍

```python
# decepticon/channels/discord_notifier.py

class DiscordNotifier:
    """RedGate 이벤트를 Discord에 실시간 전달."""
    
    async def stream_objective(self, thread_id: str, objective_id: str, events):
        """목표 실행 이벤트를 Discord 스레드에 스트리밍."""
        thread = self.bot.get_channel(int(thread_id))
        
        async for event in events:
            match event.type:
                case "tool_start":
                    await thread.send(f"🔧 `{event.tool}` started")
                case "tool_result":
                    # 결과 요약 (Discord 2000자 제한)
                    summary = event.result[:500] + "..." if len(event.result) > 500 else event.result
                    await thread.send(f"```\n{summary}\n```")
                case "finding":
                    severity_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
                    emoji = severity_emoji.get(event.severity, "⚪")
                    await thread.send(
                        f"{emoji} **Finding**: {event.title}\n"
                        f"Target: `{event.target}`\n"
                        f"CVSS: {event.cvss}"
                    )
                case "defense_applied":
                    await thread.send(f"🛡️ Defense applied: {event.description}")
                case "immune":
                    await thread.send(f"✅ **Immune**: {event.finding_id} — re-attack blocked")
                case "objective_complete":
                    await thread.send(f"✅ Objective `{objective_id}` completed")
    
    async def send_alert(self, finding: Finding):
        """CRITICAL/HIGH Finding 즉시 알림."""
        channel = self.bot.get_channel(int(self.config.discord.channels.alerts))
        
        embed = discord.Embed(
            title=f"{'🔴' if finding.severity == 'CRITICAL' else '🟠'} {finding.title}",
            color=0xFF0000 if finding.severity == "CRITICAL" else 0xFF8C00,
        )
        embed.add_field(name="Target", value=finding.target, inline=True)
        embed.add_field(name="CVSS", value=str(finding.cvss_score), inline=True)
        embed.add_field(name="CWE", value=finding.cwe_id, inline=True)
        embed.add_field(name="Root Cause", value=finding.root_cause, inline=False)
        
        # 방어 액션 목록
        actions_text = "\n".join(
            f"{'🤖' if a.automatable else '👤'} {a.description}"
            for a in finding.remediation_actions
        )
        embed.add_field(name="Remediation Actions", value=actions_text, inline=False)
        
        await channel.send(embed=embed)
```

## 6. Queue & Concurrency

### 6.1 Lane-based Queue

```python
# decepticon/gateway/queue.py

import asyncio

class LaneQueue:
    """OpenClaw lane-aware FIFO 큐. asyncio 네이티브 구현."""
    
    def __init__(self):
        self.lanes: dict[str, asyncio.Semaphore] = {}
        self.global_semaphore: asyncio.Semaphore | None = None
    
    def configure(self, config: AgentPoolConfig):
        """레인별 동시성 설정."""
        self.lanes = {
            "session": {},  # per-session: 항상 1
            "main": asyncio.Semaphore(config.max_concurrent_agents),
            "sandbox": asyncio.Semaphore(config.max_concurrent_sandboxes),
            "cron": asyncio.Semaphore(2),
        }
    
    async def acquire(self, session_key: str, lane: str = "main"):
        """레인 슬롯 획득. 세션 내 순차, 글로벌 동시성 제한."""
        
        # 1. Session lane (항상 1 — 세션 내 순차)
        if session_key not in self.lanes["session"]:
            self.lanes["session"][session_key] = asyncio.Semaphore(1)
        await self.lanes["session"][session_key].acquire()
        
        # 2. Global lane
        await self.lanes[lane].acquire()
    
    def release(self, session_key: str, lane: str = "main"):
        """레인 슬롯 해제."""
        self.lanes["session"][session_key].release()
        self.lanes[lane].release()

class QueuedExecution:
    """큐잉된 에이전트 실행."""
    
    def __init__(self, queue: LaneQueue):
        self.queue = queue
    
    async def execute(self, session_key: str, func, *args, **kwargs):
        """세션 큐에서 순차 실행."""
        await self.queue.acquire(session_key)
        try:
            return await func(*args, **kwargs)
        finally:
            self.queue.release(session_key)
```

## 7. Event Streaming

### 7.1 이벤트 브로드캐스터

```python
# decepticon/gateway/events.py

class EventBroadcaster:
    """연결된 모든 클라이언트에 이벤트 브로드캐스트."""
    
    def __init__(self):
        self.subscribers: dict[str, set[str]] = {}  # event → {connId}
        self.connections: dict[str, WebSocket] = {}
        self.seq = 0
    
    async def broadcast(self, event: str, payload: dict, target_conn: str | None = None):
        """이벤트 전송. target_conn이면 특정 연결에만."""
        self.seq += 1
        frame = EventFrame(event=event, payload=payload, seq=self.seq)
        
        if target_conn:
            ws = self.connections.get(target_conn)
            if ws:
                await ws.send_json(frame.model_dump())
        else:
            # 모든 구독자에게 전송 (실패 무시)
            for conn_id in self.subscribers.get(event, set()):
                ws = self.connections.get(conn_id)
                if ws:
                    try:
                        await ws.send_json(frame.model_dump())
                    except Exception:
                        pass  # 끊긴 연결 무시
    
    async def emit_finding(self, finding: Finding):
        await self.broadcast("finding", finding.model_dump())
    
    async def emit_defense(self, defense_id: str, status: str, details: str):
        await self.broadcast("defense", {
            "defenseId": defense_id, "status": status, "details": details
        })
    
    async def emit_objective(self, objective_id: str, status: str, progress: dict):
        await self.broadcast("objective", {
            "objectiveId": objective_id, "status": status, **progress
        })
```

## 8. State Persistence

### 8.1 상태 저장소

```python
# decepticon/gateway/state.py

import aiosqlite

class GatewayState:
    """게이트웨이 상태 영속화. red-run SQLite 패턴 참조."""
    
    def __init__(self, db_path: str = "~/.decepticon/gateway/state.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS engagements (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    roe_path TEXT,
                    opplan_path TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS findings (
                    id TEXT PRIMARY KEY,
                    engagement_id TEXT REFERENCES engagements(id),
                    title TEXT NOT NULL,
                    severity TEXT,
                    cvss_score REAL,
                    target TEXT,
                    cwe_id TEXT,
                    status TEXT DEFAULT 'discovered',
                    evidence_path TEXT,
                    discovered_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS remediations (
                    id TEXT PRIMARY KEY,
                    finding_id TEXT REFERENCES findings(id),
                    type TEXT,
                    target_system TEXT,
                    status TEXT DEFAULT 'pending',
                    applied_at TEXT,
                    verified_at TEXT,
                    immune BOOLEAN DEFAULT FALSE
                );
                
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    engagement_id TEXT REFERENCES engagements(id),
                    objective_id TEXT,
                    agent_type TEXT,
                    session_key TEXT,
                    status TEXT DEFAULT 'queued',
                    started_at TEXT,
                    ended_at TEXT
                );
                
                CREATE TABLE IF NOT EXISTS cron_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    task TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT TRUE,
                    last_run TEXT,
                    next_run TEXT
                );
            """)
```

## 9. Deployment

### 9.1 Docker Compose (확장)

```yaml
# docker-compose.yml (RedGate 추가)
services:
  redgate:
    build:
      context: .
      dockerfile: containers/redgate.Dockerfile
    ports:
      - "18789:18789"
    environment:
      - DECEPTICON_AUTH_TOKEN=${DECEPTICON_AUTH_TOKEN}
      - DECEPTICON_DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN}
      - DECEPTICON_MODEL_PROFILE=ECO
    volumes:
      - ~/.decepticon:/home/app/.decepticon
      - /var/run/docker.sock:/var/run/docker.sock  # sandbox 관리
    depends_on:
      - litellm
    restart: unless-stopped
    
  # 기존 서비스 유지
  litellm:
    # ... (기존 설정)
  
  sandbox:
    # ... (기존 Kali sandbox)
```

### 9.2 systemd 데몬

```ini
# /etc/systemd/user/decepticon-redgate.service
[Unit]
Description=Decepticon RedGate Control Plane
After=network.target docker.service

[Service]
Type=simple
ExecStart=/usr/bin/python -m decepticon.gateway --bind 127.0.0.1 --port 18789
Restart=always
RestartSec=5
Environment=DECEPTICON_AUTH_TOKEN=your-secret-token

[Install]
WantedBy=default.target
```

## 10. File Structure

```
decepticon/
  gateway/                    (신규 — RedGate)
    __init__.py
    server.py                 # FastAPI + 메인 서버
    ws_handler.py             # WebSocket 핸들러
    protocol.py               # JSON-RPC 프레임 스키마
    rpc_methods.py            # RPC 메서드 라우터
    auth.py                   # 인증 해석
    config.py                 # RedGateConfig
    config_watcher.py         # Hot-reload (watchdog)
    queue.py                  # Lane-based 큐
    events.py                 # 이벤트 브로드캐스터
    state.py                  # SQLite 상태 저장소
    session.py                # 세션 관리
    routing.py                # 인게이지먼트 라우팅
  
  channels/                   (신규 — 채널 통합)
    __init__.py
    discord_bot.py            # Discord 봇
    discord_notifier.py       # 이벤트 → Discord
    discord_auth.py           # 운영자 인증
    base.py                   # 채널 추상 클래스
  
  # 기존 디렉토리 유지
  agents/                     # 공격형 에이전트 (기존)
  backends/                   # Docker sandbox (기존)
  middleware/                  # OPPLAN 등 (기존)
  llm/                        # LLM factory (기존)
  core/                       # 설정, 스키마 (기존)
```

## 11. 구현 순서

```
Week 1: 기반
  ├── gateway/protocol.py (프레임 스키마)
  ├── gateway/auth.py (인증)
  ├── gateway/server.py + ws_handler.py (WS 서버)
  └── 테스트: WS 연결 + 핸드셰이크

Week 2: Discord
  ├── channels/discord_bot.py (봇 기본)
  ├── channels/discord_notifier.py (이벤트 전달)
  ├── channels/discord_auth.py (운영자 인증)
  └── 테스트: Discord 명령 → RedGate RPC

Week 3: 큐 + 이벤트
  ├── gateway/queue.py (레인 큐)
  ├── gateway/events.py (브로드캐스터)
  ├── gateway/state.py (SQLite)
  └── 테스트: 병렬 에이전트 실행

Week 4: 통합
  ├── rpc_methods.py (모든 메서드)
  ├── config_watcher.py (hot-reload)
  ├── Docker Compose 업데이트
  └── E2E 테스트: Discord → RedGate → Agent → Discord
```
