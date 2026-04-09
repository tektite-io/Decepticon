# Hardening Loop Engine — Implementation Guide

> Ralph Loop Engine + Cron 스케줄링 + Discord 통합 + 수렴 메트릭 구현 전략

## 1. Ralph Loop Engine (핵심)

### 1.1 엔진 구현

```python
# decepticon/ralph/engine.py

import asyncio
from datetime import datetime

class RalphLoopEngine:
    """Universal Ralph Loop Engine.
    
    Plan → Pick → Execute → Verify → Mark → Repeat
    
    PlanAdapter를 받아 어떤 도메인이든 자율 실행.
    """
    
    def __init__(
        self,
        adapter: PlanAdapter,
        agent_pool: AgentPool,
        notifier: DiscordNotifier | None = None,
        hook_engine: OPSECHookEngine | None = None,
        kg: AttackDefenseKG | None = None,
        config: RalphConfig = RalphConfig(),
    ):
        self.adapter = adapter
        self.agent_pool = agent_pool
        self.notifier = notifier
        self.hook_engine = hook_engine
        self.kg = kg
        self.config = config
        self.metrics = HardeningMetrics()
        self.state = LoopState()
    
    async def run(self, plan_source: str) -> LoopResult:
        """메인 루프. 수렴 또는 최대 반복까지 실행."""
        
        # 1. 상태 복구 (crash recovery)
        if self.state.checkpoint_exists(plan_source):
            self.state = LoopState.load(plan_source)
            items = self.state.items
            iteration = self.state.last_iteration + 1
            log.info(f"Resumed from iteration {iteration}")
        else:
            items = self.adapter.load(plan_source)
            iteration = 1
        
        await self._notify(f"Ralph Loop started. {len(items)} items loaded.")
        
        # 2. 메인 루프
        for i in range(iteration, self.config.max_iterations + 1):
            self.state.last_iteration = i
            self.state.items = items
            self.state.save(plan_source)  # 체크포인트
            
            # 수렴 체크
            should_stop, reason = self.config.convergence.should_stop(self.metrics)
            if should_stop:
                await self._notify(f"Converged at iteration {i}: {reason}")
                return LoopResult(success=True, reason=reason, iterations=i)
            
            # 완료 체크
            if self.adapter.is_done(items):
                await self._notify(f"All items complete after {i-1} iterations")
                return LoopResult(success=True, iterations=i-1)
            
            # 다음 항목 선택
            item = self.adapter.pick_next(items)
            if item is None:
                await self._notify("No actionable items (deadlock or all blocked)")
                return LoopResult(success=False, reason="deadlock")
            
            # 실행
            await self._notify(
                f"[{i}/{self.config.max_iterations}] "
                f"{item.id}: {item.title}"
            )
            
            item.status = ItemStatus.IN_PROGRESS
            result = await self._execute_item(item, items)
            
            # 검증
            verification = self.adapter.verify(item, result)
            
            # 마크
            self.adapter.mark_complete(item, verification)
            self.adapter.save(items, plan_source)
            
            # 메트릭 업데이트
            self._update_metrics(item, verification)
            
            # 프로그레스 기록
            self._append_progress(item, verification, i)
            
            # 알림
            status = "PASSED" if verification.passed else "BLOCKED"
            await self._notify(f"{item.id} {status}: {verification.evidence}")
        
        return LoopResult(success=False, reason="max_iterations_reached")
    
    async def _execute_item(self, item: PlanItem, all_items: list[PlanItem]) -> dict:
        """항목 실행. 레인에 따라 공격 또는 방어."""
        lane = item.metadata.get("lane", "attack")
        
        if lane == "attack":
            return await self._execute_attack(item)
        elif lane == "defense":
            return await self._execute_defense(item)
        elif lane == "verification":
            return await self._execute_verification(item)
        else:
            raise ValueError(f"Unknown lane: {lane}")
    
    async def _execute_attack(self, item: PlanItem) -> dict:
        """공격 목표 실행."""
        objective = Objective.from_plan_item(item)
        
        # OPSEC 훅
        if self.hook_engine:
            await self.hook_engine.before_execute(objective)
        
        # 에이전트 스폰 + 실행
        run = await self.agent_pool.spawn(
            objective=objective,
            roe=self.state.roe,
            engagement_workspace=self.state.workspace,
        )
        
        # 완료 대기
        await run.wait()
        
        # Finding 추출
        findings = FindingExtractor().extract(run.result, objective)
        item.metadata["findings"] = [f.model_dump() for f in findings]
        
        # KG 업데이트
        if self.kg:
            for finding in findings:
                await self.kg.store_finding(finding)
        
        # OPSEC 훅
        if self.hook_engine:
            await self.hook_engine.after_execute(objective, run.result)
        
        # Discord 알림 (Finding별)
        for finding in findings:
            if finding.severity in ("CRITICAL", "HIGH"):
                await self.notifier.send_alert(finding) if self.notifier else None
        
        return {"findings": findings, "agent_result": run.result}
    
    async def _execute_defense(self, item: PlanItem) -> dict:
        """방어 목표 실행."""
        action = RemediationAction(**item.metadata["action"])
        
        # 방어형 에이전트 선택
        agent = DefenseAgentFactory.create(action.type)
        
        # 승인 확인
        if item.metadata.get("approval") == "human_required":
            approved = await self._wait_for_approval(item)
            if not approved:
                return {"status": "rejected"}
        
        # 방어 적용
        result = await agent.apply(action, self.state.defense_config)
        
        # KG 업데이트
        if self.kg and result.success:
            await self.kg.store_remediation(
                Remediation.from_result(result), 
                item.metadata["source_finding"]
            )
        
        return {"status": "applied" if result.success else "failed", "result": result}
    
    async def _execute_verification(self, item: PlanItem) -> dict:
        """방어 검증 (재공격)."""
        source_finding = item.metadata["source_finding"]
        
        # 같은 공격 벡터로 재공격
        run = await self.agent_pool.spawn(
            objective=Objective(
                id=f"VERIFY-{source_finding}",
                title=f"Re-attack: {item.title}",
                phase="VERIFICATION",
                description=f"Verify defense for {source_finding} by re-attempting the same attack",
            ),
            roe=self.state.roe,
            engagement_workspace=self.state.workspace,
        )
        
        await run.wait()
        
        # 공격 차단됨 = immune
        attack_blocked = not any(
            f.id == source_finding for f in FindingExtractor().extract(run.result, run.objective)
        )
        
        if attack_blocked and self.kg:
            await self.kg.mark_immune(source_finding)
        
        item.metadata["immune"] = attack_blocked
        item.metadata["verified"] = True
        
        return {"attack_blocked": attack_blocked}
    
    async def _wait_for_approval(self, item: PlanItem) -> bool:
        """Discord에서 인간 승인 대기."""
        if not self.notifier:
            return True  # notifier 없으면 자동 승인
        
        await self.notifier.request_approval(item)
        
        # 승인 이벤트 대기 (최대 24시간)
        try:
            approved = await asyncio.wait_for(
                self.state.approval_events.get(item.id),
                timeout=86400,
            )
            return approved
        except asyncio.TimeoutError:
            await self._notify(f"Approval timeout for {item.id}, skipping")
            return False
```

## 2. PlanAdapter Wiring

### 2.1 Adapter 선택 로직

```python
# decepticon/ralph/adapter_factory.py

class PlanAdapterFactory:
    """사용 시나리오에 따라 적절한 PlanAdapter 생성."""
    
    @staticmethod
    def create(mode: str, config: dict) -> PlanAdapter:
        match mode:
            case "attack":
                # 공격만 (기존 Decepticon)
                return OPPLANAdapter()
            
            case "defense":
                # 방어만 (기존 Finding에서)
                return DefenseOPPLANAdapter()
            
            case "hardening":
                # 공격 + 방어 통합 (Offensive Vaccine)
                return AttackDefensePlanAdapter(
                    roe=RulesOfEngagement.load(config["roe_path"]),
                )
            
            case "bugbounty":
                # 버그바운티 스코프 기반
                return BugBountyAdapter()
            
            case "continuous":
                # 지속적 모니터링 (정찰만 반복)
                return ContinuousReconAdapter()
```

### 2.2 CLI 엔트리포인트

```python
# decepticon/cli/ralph_command.py

import click

@click.command()
@click.argument("mode", type=click.Choice(["attack", "defense", "hardening", "bugbounty"]))
@click.option("--plan", type=click.Path(exists=True), help="Plan document path")
@click.option("--max-iterations", default=100, help="Maximum loop iterations")
@click.option("--discord/--no-discord", default=True, help="Enable Discord notifications")
@click.option("--schedule", default=None, help="Cron schedule (e.g., '0 22 * * *')")
def ralph(mode, plan, max_iterations, discord, schedule):
    """Decepticon Ralph Loop — autonomous security hardening."""
    
    # Adapter 생성
    adapter = PlanAdapterFactory.create(mode, {"roe_path": plan})
    
    # Engine 구성
    engine = RalphLoopEngine(
        adapter=adapter,
        agent_pool=AgentPool(config.agent_pool, SandboxPool(config)),
        notifier=DiscordNotifier(config) if discord else None,
        hook_engine=OPSECHookEngine(config),
        kg=AttackDefenseKG(config.neo4j) if config.neo4j else None,
        config=RalphConfig(max_iterations=max_iterations),
    )
    
    if schedule:
        # Cron 모드: 스케줄에 따라 반복 실행
        scheduler = ScanScheduler(config)
        scheduler.add_job(
            name=f"ralph-{mode}",
            schedule=schedule,
            func=lambda: asyncio.run(engine.run(plan)),
        )
        scheduler.run_forever()
    else:
        # 즉시 실행
        asyncio.run(engine.run(plan))

# 사용 예시:
# decepticon ralph attack --plan /workspace/acme/opplan.json
# decepticon ralph hardening --plan /workspace/acme/ --schedule "0 22 * * *"
# decepticon ralph bugbounty --plan /workspace/hackerone-scope.json
```

## 3. Cron Scheduling

### 3.1 스케줄러 구현

```python
# decepticon/ralph/scheduler.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

class ScanScheduler:
    """OpenClaw CronService 패턴. APScheduler 기반."""
    
    def __init__(self, config: SchedulerConfig):
        self.config = config
        self.scheduler = AsyncIOScheduler(timezone=config.timezone)
        self.jobs: dict[str, ScheduledJob] = {}
    
    def add_job(
        self,
        name: str,
        schedule: str,
        func: Callable,
        params: dict | None = None,
        announce_channel: str | None = None,
    ):
        """Cron 작업 추가."""
        trigger = CronTrigger.from_crontab(schedule, timezone=self.config.timezone)
        
        job = self.scheduler.add_job(
            self._wrapped_execution,
            trigger=trigger,
            id=name,
            kwargs={
                "name": name,
                "func": func,
                "params": params or {},
                "announce_channel": announce_channel,
            },
        )
        
        self.jobs[name] = ScheduledJob(
            name=name,
            schedule=schedule,
            func=func,
            apscheduler_job=job,
        )
    
    async def _wrapped_execution(self, name, func, params, announce_channel):
        """실행 래퍼: 시작/완료 알림 + 에러 핸들링."""
        log.info(f"Cron job '{name}' starting")
        
        if announce_channel and self.notifier:
            await self.notifier.send_to_channel(
                announce_channel, f"🕐 Scheduled job `{name}` starting"
            )
        
        try:
            result = await func(**params)
            
            if announce_channel and self.notifier:
                await self.notifier.send_to_channel(
                    announce_channel,
                    f"✅ Job `{name}` completed: {result.summary if hasattr(result, 'summary') else 'OK'}"
                )
        except Exception as e:
            log.error(f"Cron job '{name}' failed: {e}")
            
            if announce_channel and self.notifier:
                await self.notifier.send_to_channel(
                    announce_channel, f"❌ Job `{name}` failed: {str(e)[:200]}"
                )
    
    def start(self):
        self.scheduler.start()
    
    def stop(self):
        self.scheduler.shutdown()
    
    # === 기본 스케줄 프리셋 ===
    
    def setup_hardening_presets(self, engine: RalphLoopEngine, plan_source: str):
        """지속적 강화 프리셋 스케줄."""
        
        # 야간 전체 사이클
        self.add_job(
            name="nightly-hardening",
            schedule=f"0 {self.config.night_window_start.split(':')[0]} * * *",
            func=engine.run,
            params={"plan_source": plan_source},
            announce_channel="reports",
        )
        
        # 6시간마다 정찰
        self.add_job(
            name="periodic-recon",
            schedule="0 */6 * * *",
            func=self._recon_only,
            params={"plan_source": plan_source},
            announce_channel="attack_log",
        )
        
        # 주간 수렴 보고서
        self.add_job(
            name="weekly-convergence",
            schedule="0 9 * * 1",
            func=self._convergence_report,
            params={"plan_source": plan_source},
            announce_channel="reports",
        )
```

### 3.2 Night Window 운용

```python
# decepticon/ralph/night_window.py

class NightWindowManager:
    """야간 윈도우 관리. 레드팀 작전은 특정 시간대에만."""
    
    def __init__(self, config: SchedulerConfig):
        self.start_hour = int(config.night_window_start.split(":")[0])
        self.end_hour = int(config.night_window_end.split(":")[0])
        self.tz = ZoneInfo(config.timezone)
    
    def is_within_window(self) -> bool:
        """현재 시간이 야간 윈도우 내인지."""
        now = datetime.now(self.tz).hour
        if self.start_hour > self.end_hour:  # 22:00-06:00
            return now >= self.start_hour or now < self.end_hour
        else:  # 09:00-17:00
            return self.start_hour <= now < self.end_hour
    
    async def wait_for_window(self):
        """윈도우 시작까지 대기."""
        while not self.is_within_window():
            now = datetime.now(self.tz)
            if now.hour < self.start_hour:
                wait_hours = self.start_hour - now.hour
            else:
                wait_hours = (24 - now.hour) + self.start_hour
            
            log.info(f"Outside night window. Waiting {wait_hours}h until {self.start_hour}:00")
            await asyncio.sleep(min(wait_hours * 3600, 3600))  # 최대 1시간 단위 체크
    
    def time_remaining(self) -> int:
        """윈도우 남은 시간 (초)."""
        if not self.is_within_window():
            return 0
        now = datetime.now(self.tz)
        if self.end_hour > now.hour:
            return (self.end_hour - now.hour) * 3600
        else:
            return ((24 - now.hour) + self.end_hour) * 3600
```

## 4. Discord Integration (Deep)

### 4.1 채널 구조

```python
# decepticon/channels/discord_setup.py

class DiscordChannelSetup:
    """Discord 서버 채널 자동 생성."""
    
    CHANNEL_SPEC = {
        "engagement-control": {
            "topic": "인게이지먼트 시작/중단/설정",
            "permissions": "admin",
        },
        "attack-log": {
            "topic": "공격 진행 상황 실시간 로그",
            "permissions": "operator",
        },
        "defense-log": {
            "topic": "방어 적용 상황 실시간 로그",
            "permissions": "operator",
        },
        "findings": {
            "topic": "발견된 취약점 보고",
            "permissions": "viewer",
        },
        "alerts": {
            "topic": "CRITICAL/HIGH 즉시 알림",
            "permissions": "viewer",
        },
        "approvals": {
            "topic": "방어 액션 승인 대기",
            "permissions": "operator",
        },
        "reports": {
            "topic": "일간/주간 수렴 보고서",
            "permissions": "viewer",
        },
    }
```

### 4.2 Discord 명령어

```python
# decepticon/channels/discord_commands.py

class DiscordCommands:
    """Discord 슬래시 명령어."""
    
    @app_commands.command(name="engagement", description="인게이지먼트 관리")
    async def engagement(self, interaction, action: str, target: str = None):
        match action:
            case "start":
                result = await self.gate.start_engagement(target)
                await interaction.response.send_message(f"Engagement started: {result.name}")
            case "stop":
                await self.gate.stop_engagement()
                await interaction.response.send_message("Engagement stopped")
            case "status":
                status = await self.gate.engagement_status()
                embed = self._format_status_embed(status)
                await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="ralph", description="Ralph Loop 제어")
    async def ralph_cmd(self, interaction, action: str):
        match action:
            case "start":
                await interaction.response.send_message("Starting Ralph Loop...")
                asyncio.create_task(self.gate.start_ralph_loop())
            case "stop":
                await self.gate.stop_ralph_loop()
                await interaction.response.send_message("Ralph Loop stopped")
            case "status":
                metrics = self.gate.ralph_metrics()
                await interaction.response.send_message(self._format_metrics(metrics))
    
    @app_commands.command(name="approve", description="방어 액션 승인")
    async def approve(self, interaction, defense_id: str):
        await self.gate.approve_defense(defense_id, str(interaction.user.id))
        await interaction.response.send_message(f"✅ {defense_id} approved")
    
    @app_commands.command(name="findings", description="현재 Finding 목록")
    async def findings(self, interaction, severity: str = "all"):
        findings = await self.gate.list_findings(severity)
        embed = self._format_findings_embed(findings)
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="convergence", description="수렴 상태")
    async def convergence(self, interaction):
        metrics = self.gate.ralph_metrics()
        chart = self._generate_convergence_chart(metrics)
        await interaction.response.send_message(
            f"Convergence: {metrics.convergence_rate:.0%}",
            file=discord.File(chart, "convergence.png"),
        )
```

## 5. Metrics & Convergence

### 5.1 메트릭 수집기

```python
# decepticon/ralph/metrics.py

@dataclass
class HardeningMetrics:
    total_objectives: int = 0
    completed_objectives: int = 0
    total_findings: int = 0
    total_remediations: int = 0
    verified_immune: int = 0
    findings_per_iteration: list[int] = field(default_factory=list)
    total_iterations: int = 0
    total_runtime_seconds: float = 0
    severity_distribution: dict[str, int] = field(default_factory=dict)
    immune_by_severity: dict[str, int] = field(default_factory=dict)
    
    @property
    def convergence_rate(self) -> float:
        if self.total_findings == 0:
            return 1.0
        return self.verified_immune / self.total_findings
    
    @property
    def is_converged(self) -> bool:
        if len(self.findings_per_iteration) < 3:
            return False
        return all(f == 0 for f in self.findings_per_iteration[-3:])
    
    def to_discord_embed(self) -> dict:
        """Discord Embed 형식으로 변환."""
        return {
            "title": "Hardening Metrics",
            "fields": [
                {"name": "Convergence", "value": f"{self.convergence_rate:.0%}", "inline": True},
                {"name": "Findings", "value": str(self.total_findings), "inline": True},
                {"name": "Immune", "value": str(self.verified_immune), "inline": True},
                {"name": "Iterations", "value": str(self.total_iterations), "inline": True},
                {"name": "Trend", "value": self._trend_emoji(), "inline": True},
            ],
        }
    
    def _trend_emoji(self) -> str:
        if len(self.findings_per_iteration) < 2:
            return "📊 Insufficient data"
        diff = self.findings_per_iteration[-1] - self.findings_per_iteration[-2]
        if diff < 0: return "📉 Improving"
        if diff == 0 and self.findings_per_iteration[-1] == 0: return "✅ Converged"
        if diff > 0: return "📈 Degrading"
        return "➡️ Stable"

class ConvergenceCriteria:
    """수렴 판단 기준."""
    
    def __init__(
        self,
        max_iterations: int = 100,
        max_runtime_hours: float = 48.0,
        zero_findings_streak: int = 3,
        min_immunity_rate: float = 0.95,
    ):
        self.max_iterations = max_iterations
        self.max_runtime_hours = max_runtime_hours
        self.zero_findings_streak = zero_findings_streak
        self.min_immunity_rate = min_immunity_rate
    
    def should_stop(self, metrics: HardeningMetrics) -> tuple[bool, str]:
        if metrics.is_converged:
            return True, f"converged: zero findings for {self.zero_findings_streak} consecutive iterations"
        if metrics.convergence_rate >= self.min_immunity_rate:
            return True, f"immunity rate {metrics.convergence_rate:.0%} >= {self.min_immunity_rate:.0%}"
        if metrics.total_iterations >= self.max_iterations:
            return True, f"max iterations: {self.max_iterations}"
        if metrics.total_runtime_seconds >= self.max_runtime_hours * 3600:
            return True, f"max runtime: {self.max_runtime_hours}h"
        return False, "continuing"
```

### 5.2 보고서 생성기

```python
# decepticon/ralph/reports.py

class HardeningReportGenerator:
    """수렴 보고서 자동 생성."""
    
    async def generate(self, metrics: HardeningMetrics, findings: list[Finding]) -> str:
        """Markdown 보고서 생성."""
        
        report = f"""# Hardening Report — {datetime.now().strftime('%Y-%m-%d')}

## Summary
- **Cycle**: #{metrics.total_iterations}
- **Duration**: {metrics.total_runtime_seconds/3600:.1f}h
- **Convergence**: {metrics.convergence_rate:.0%}
- **Trend**: {metrics._trend_emoji()}

## Findings ({metrics.total_findings} total)

| ID | Severity | Target | Status |
|----|----------|--------|--------|
"""
        for f in findings:
            status = "immune ✅" if f.status == "immune" else f.status
            report += f"| {f.id} | {f.severity} | {f.target} | {status} |\n"
        
        report += f"""
## Severity Breakdown

| Severity | Found | Immune | Rate |
|----------|-------|--------|------|
"""
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            found = metrics.severity_distribution.get(sev, 0)
            immune = metrics.immune_by_severity.get(sev, 0)
            rate = f"{immune/found*100:.0f}%" if found > 0 else "N/A"
            report += f"| {sev} | {found} | {immune} | {rate} |\n"
        
        report += f"""
## Trend (Findings per iteration)
{self._ascii_chart(metrics.findings_per_iteration)}

## Next Actions
"""
        # 미면역 항목 나열
        unimmune = [f for f in findings if f.status != "immune"]
        if unimmune:
            for f in unimmune[:5]:
                report += f"- [ ] {f.id}: {f.title} ({f.severity})\n"
        else:
            report += "- All findings are immune. System is hardened. ✅\n"
        
        return report
    
    def _ascii_chart(self, data: list[int]) -> str:
        if not data:
            return "No data"
        max_val = max(data) or 1
        chart = "```\n"
        for i, val in enumerate(data):
            bar = "█" * int(val / max_val * 20)
            chart += f"  Iter {i+1:2d}: {bar} ({val})\n"
        chart += "```"
        return chart
```

## 6. State Persistence (Crash Recovery)

### 6.1 Loop State

```python
# decepticon/ralph/state.py

import json
from pathlib import Path

@dataclass
class LoopState:
    """Ralph Loop 상태 영속화. crash recovery 지원."""
    
    items: list[PlanItem] = field(default_factory=list)
    last_iteration: int = 0
    current_phase: str = "idle"  # idle, recon, attack, defense, verify
    roe: RulesOfEngagement | None = None
    workspace: str = ""
    defense_config: DefenseConfig | None = None
    metrics: HardeningMetrics = field(default_factory=HardeningMetrics)
    approval_events: dict[str, asyncio.Event] = field(default_factory=dict)
    started_at: str = ""
    last_checkpoint: str = ""
    
    def save(self, plan_source: str):
        """체크포인트 저장."""
        state_path = Path(plan_source).parent / ".ralph-state.json"
        self.last_checkpoint = datetime.now().isoformat()
        
        state_dict = {
            "items": [item.to_dict() for item in self.items],
            "last_iteration": self.last_iteration,
            "current_phase": self.current_phase,
            "workspace": self.workspace,
            "metrics": asdict(self.metrics),
            "started_at": self.started_at,
            "last_checkpoint": self.last_checkpoint,
        }
        
        # 원자적 쓰기 (tmp → rename)
        tmp_path = state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(state_dict, indent=2, default=str))
        tmp_path.rename(state_path)
    
    @classmethod
    def load(cls, plan_source: str) -> "LoopState":
        """체크포인트에서 복구."""
        state_path = Path(plan_source).parent / ".ralph-state.json"
        data = json.loads(state_path.read_text())
        
        state = cls()
        state.items = [PlanItem.from_dict(d) for d in data["items"]]
        state.last_iteration = data["last_iteration"]
        state.current_phase = data["current_phase"]
        state.workspace = data["workspace"]
        state.metrics = HardeningMetrics(**data["metrics"])
        state.started_at = data["started_at"]
        state.last_checkpoint = data["last_checkpoint"]
        return state
    
    def checkpoint_exists(self, plan_source: str) -> bool:
        state_path = Path(plan_source).parent / ".ralph-state.json"
        return state_path.exists()
```

## 7. 전체 파일 구조

```
decepticon/
  ralph/                          # Ralph Loop Engine
    __init__.py
    engine.py                     # RalphLoopEngine (핵심)
    adapters/
      __init__.py
      base.py                     # PlanAdapter ABC
      opplan.py                   # OPPLANAdapter (공격)
      defense.py                  # DefenseOPPLANAdapter (방어)
      attack_defense.py           # AttackDefensePlanAdapter (통합)
      bugbounty.py                # BugBountyAdapter
      continuous_recon.py         # ContinuousReconAdapter
    adapter_factory.py            # PlanAdapterFactory
    scheduler.py                  # ScanScheduler (APScheduler)
    night_window.py               # NightWindowManager
    state.py                      # LoopState (crash recovery)
    metrics.py                    # HardeningMetrics + ConvergenceCriteria
    reports.py                    # HardeningReportGenerator
  
  feedback/                       # Feedback Pipeline
    __init__.py
    extractor.py                  # FindingExtractor
    defense_planner.py            # DefensePlanner
    parsers/
      nuclei.py                   # Nuclei JSON parser
      nmap.py                     # Nmap XML parser
      sqlmap.py                   # SQLMap output parser
  
  defense/                        # Defensive Agents
    __init__.py
    base.py                       # DefensiveAgent ABC
    waf_agent.py                  # WAF 규칙 관리
    patch_agent.py                # 코드 패치 생성
    config_agent.py               # 설정 강화
    detection_agent.py            # Sigma 규칙 생성
    factory.py                    # DefenseAgentFactory
    backends/
      modsecurity.py              # ModSecurity backend
      cloudflare.py               # Cloudflare API
      ansible.py                  # Ansible playbook
  
  gateway/                        # RedGate Control Plane
    # ... (redgate-control-plane.md 참조)
  
  channels/                       # Channel Integration
    # ... (redgate-control-plane.md 참조)
```

## 8. 기술 의사결정 요약

| 결정 | 선택 | 대안 | 근거 |
|------|------|------|------|
| WS 서버 | FastAPI | Starlette, aiohttp | Pydantic 통합, 자동 문서화 |
| 스케줄러 | APScheduler | Celery, schedule | 경량, asyncio 네이티브, cron 지원 |
| State DB | SQLite | PostgreSQL, Redis | 서버리스, 단일 파일, red-run 검증 |
| Discord | discord.py | nextcord, hikari | 성숙도, 문서, 커뮤니티 |
| WAF API | 직접 HTTP | Ansible | 즉시 적용 (Ansible은 배치) |
| SIEM | Sigma → 변환 | 직접 SPL/EQL | 포터블, 멀티 SIEM |
| KG | Neo4j | SQLite+JSON | 관계 쿼리, 기존 인프라 |
| Auth | JWT + shared-secret | OAuth2 | 단순, 충분, 오버엔지니어링 방지 |
| Config watch | watchdog | inotify 직접 | 크로스 플랫폼, 안정 |
| Crash recovery | JSON checkpoint | SQLite WAL | 단순, 원자적 쓰기 |

## 9. 구현 전체 로드맵

```
Month 1: Foundation
  Week 1-2: RedGate (WS + Auth + Config)
  Week 3-4: Discord (Bot + Notifier + Commands)

Month 2: Attack Enhancement
  Week 5-6: AgentPool (병렬 실행 + SandboxPool)
  Week 7-8: Ralph Engine (Loop + OPPLANAdapter)

Month 3: Feedback + Defense
  Week 9-10: FindingExtractor + DefensePlanner
  Week 11-12: WAFAgent + DetectionAgent + ConfigAgent

Month 4: Integration + Hardening
  Week 13-14: AttackDefensePlanAdapter + 수렴 메트릭
  Week 15-16: E2E 테스트 + Night Window + Cron

Month 5: Polish
  Week 17-18: PatchAgent (LLM coding)
  Week 19-20: Dashboard + 보고서 + 문서
```
