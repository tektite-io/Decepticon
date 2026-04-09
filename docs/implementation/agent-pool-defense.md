# Agent Pool & Defensive Agents — Implementation Guide

> 병렬 에이전트 풀, 방어형 에이전트, 피드백 파이프라인, KG 통합 구현 전략

## 1. Agent Pool (병렬 에이전트 풀)

### 1.1 현재 vs 목표

```
현재 Decepticon:
  Decepticon Agent (orchestrator)
    → SubAgentMiddleware → recon agent (순차)
    → SubAgentMiddleware → exploit agent (순차)
    → 한번에 하나의 서브에이전트만 실행

목표:
  RedGate
    → AgentPool
      → sandbox-01: recon agent (병렬)
      → sandbox-02: exploit agent (병렬)
      → sandbox-03: postexploit agent (병렬)
      → 최대 N개 동시 실행
```

### 1.2 구현

```python
# decepticon/gateway/agent_pool.py

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

@dataclass
class AgentRun:
    """활성 에이전트 실행 인스턴스."""
    id: str = field(default_factory=lambda: str(uuid4()))
    objective_id: str = ""
    agent_type: str = ""          # recon, exploit, postexploit, ...
    session_key: str = ""
    sandbox_id: str = ""
    status: str = "queued"        # queued → running → completed → failed
    started_at: datetime | None = None
    ended_at: datetime | None = None
    findings: list[dict] = field(default_factory=list)
    task: asyncio.Task | None = None

class AgentPool:
    """병렬 에이전트 풀. OpenClaw sessions_spawn + subagent 패턴."""
    
    def __init__(self, config: AgentPoolConfig, sandbox_pool: SandboxPool):
        self.config = config
        self.sandbox_pool = sandbox_pool
        self.active_runs: dict[str, AgentRun] = {}
        self.queue = LaneQueue()
        self.queue.configure(config)
    
    async def spawn(
        self,
        objective: Objective,
        roe: RulesOfEngagement,
        engagement_workspace: str,
    ) -> AgentRun:
        """목표에 맞는 에이전트를 독립 세션으로 스폰."""
        
        # 1. 에이전트 타입 결정
        agent_type = self._resolve_agent_type(objective)
        
        # 2. 세션 키 생성 (OpenClaw 패턴)
        session_key = f"engagement:{objective.engagement}:{objective.phase}:{objective.id}"
        
        # 3. Sandbox 할당
        sandbox = await self.sandbox_pool.acquire()
        
        # 4. AgentRun 생성
        run = AgentRun(
            objective_id=objective.id,
            agent_type=agent_type,
            session_key=session_key,
            sandbox_id=sandbox.id,
        )
        self.active_runs[run.id] = run
        
        # 5. 비동기 실행 (즉시 반환)
        run.task = asyncio.create_task(
            self._execute(run, objective, roe, sandbox, engagement_workspace)
        )
        
        return run
    
    async def _execute(
        self, run: AgentRun, objective, roe, sandbox, workspace
    ):
        """에이전트 실행 (큐잉 + 실행 + 정리)."""
        await self.queue.acquire(run.session_key, lane="main")
        
        try:
            run.status = "running"
            run.started_at = datetime.now()
            
            # OPSEC 훅: 실행 전 검증
            await self.hook_engine.before_execute(objective)
            
            # 에이전트 생성 (LangGraph create_agent)
            agent = self._create_agent(run.agent_type, sandbox, roe, workspace)
            
            # 실행 (스트리밍)
            result = await agent.ainvoke({
                "messages": [{"role": "user", "content": objective.to_prompt()}],
            })
            
            # 결과 처리
            run.findings = self._extract_findings(result)
            run.status = "completed"
            
            # OPSEC 훅: 실행 후 처리
            await self.hook_engine.after_execute(objective, result)
            
        except Exception as e:
            run.status = "failed"
            log.error(f"Agent run {run.id} failed: {e}")
        finally:
            run.ended_at = datetime.now()
            self.queue.release(run.session_key, lane="main")
            await self.sandbox_pool.release(sandbox)
    
    def _resolve_agent_type(self, objective: Objective) -> str:
        """킬체인 페이즈에서 에이전트 타입 결정."""
        return {
            "RECON": "recon",
            "INITIAL_ACCESS": "exploit",
            "POST_EXPLOIT": "postexploit",
            "C2": "postexploit",
            "EXFILTRATION": "postexploit",
        }.get(objective.phase, "recon")
    
    # === 제어 API (OpenClaw subagents 도구 패턴) ===
    
    async def list_active(self) -> list[AgentRun]:
        return [r for r in self.active_runs.values() if r.status == "running"]
    
    async def steer(self, run_id: str, message: str):
        """실행 중 에이전트에 메시지 주입."""
        run = self.active_runs.get(run_id)
        if run and run.status == "running":
            # LangGraph state에 메시지 주입
            await run.agent.ainject_message(message)
    
    async def kill(self, run_id: str):
        """에이전트 강제 종료."""
        run = self.active_runs.get(run_id)
        if run and run.task:
            run.task.cancel()
            run.status = "killed"
```

### 1.3 Sandbox Pool

```python
# decepticon/gateway/sandbox_pool.py

class SandboxPool:
    """Docker Kali sandbox 풀 관리."""
    
    def __init__(self, config: AgentPoolConfig, docker_config: DockerConfig):
        self.max_sandboxes = config.max_concurrent_sandboxes
        self.semaphore = asyncio.Semaphore(self.max_sandboxes)
        self.active: dict[str, DockerSandbox] = {}
        self.docker_config = docker_config
    
    async def acquire(self) -> DockerSandbox:
        """사용 가능한 sandbox 획득 (없으면 대기)."""
        await self.semaphore.acquire()
        
        sandbox = DockerSandbox(self.docker_config)
        await sandbox.start()
        self.active[sandbox.id] = sandbox
        return sandbox
    
    async def release(self, sandbox: DockerSandbox):
        """sandbox 반환 + 정리."""
        await sandbox.cleanup()
        self.active.pop(sandbox.id, None)
        self.semaphore.release()
    
    async def status(self) -> dict:
        return {
            "active": len(self.active),
            "max": self.max_sandboxes,
            "available": self.max_sandboxes - len(self.active),
        }
```

## 2. Feedback Pipeline

### 2.1 Finding 추출기

```python
# decepticon/feedback/extractor.py

class FindingExtractor:
    """에이전트 실행 결과에서 Finding 자동 추출."""
    
    # CWE → RemediationType 매핑
    CWE_REMEDIATION_MAP = {
        "CWE-89":  [RemediationType.WAF_RULE, RemediationType.CODE_PATCH],    # SQLi
        "CWE-79":  [RemediationType.WAF_RULE, RemediationType.CONFIG],        # XSS
        "CWE-200": [RemediationType.CONFIG],                                   # Info Disclosure
        "CWE-284": [RemediationType.CODE_PATCH],                              # Access Control
        "CWE-918": [RemediationType.WAF_RULE, RemediationType.CONFIG],        # SSRF
        "CWE-502": [RemediationType.CODE_PATCH],                              # Deserialization
        "CWE-22":  [RemediationType.WAF_RULE, RemediationType.CODE_PATCH],    # Path Traversal
        "CWE-798": [RemediationType.CONFIG, RemediationType.CODE_PATCH],      # Hardcoded Creds
        "CWE-306": [RemediationType.CODE_PATCH],                              # Missing Auth
        "CWE-732": [RemediationType.CONFIG],                                   # Permission
    }
    
    async def extract(self, agent_result: dict, objective: Objective) -> list[Finding]:
        """에이전트 결과에서 Finding 추출."""
        findings = []
        
        # 1. 도구별 파서로 자동 추출
        for tool_output in agent_result.get("tool_outputs", []):
            parsed = await self._parse_tool_output(tool_output)
            findings.extend(parsed)
        
        # 2. LLM 판단에서 추출 (에이전트가 명시적으로 보고한 것)
        for msg in agent_result.get("messages", []):
            if hasattr(msg, "content") and "VULNERABILITY" in str(msg.content):
                finding = await self._parse_agent_judgment(msg)
                if finding:
                    findings.append(finding)
        
        # 3. 중복 제거 (같은 target + CWE)
        findings = self._deduplicate(findings)
        
        # 4. Remediation 액션 자동 생성
        for finding in findings:
            finding.remediation_actions = self._generate_remediations(finding)
        
        return findings
    
    async def _parse_tool_output(self, output: ToolOutput) -> list[Finding]:
        """도구별 출력 파싱."""
        match output.tool:
            case "nuclei":
                return self._parse_nuclei_json(output.result)
            case "nmap":
                return self._parse_nmap_xml(output.result)
            case "sqlmap":
                return self._parse_sqlmap_output(output.result)
            case "nikto":
                return self._parse_nikto_output(output.result)
            case _:
                return []
    
    def _parse_nuclei_json(self, result: str) -> list[Finding]:
        """Nuclei JSON 출력 → Finding 목록."""
        findings = []
        for line in result.strip().split("\n"):
            try:
                entry = json.loads(line)
                findings.append(Finding(
                    id=f"FIND-{uuid4().hex[:8]}",
                    title=entry.get("info", {}).get("name", "Unknown"),
                    severity=entry.get("info", {}).get("severity", "medium").upper(),
                    cvss_score=float(entry.get("info", {}).get("classification", {}).get("cvss-score", 0)),
                    target=entry.get("host", ""),
                    endpoint=entry.get("matched-at", ""),
                    cwe_id=entry.get("info", {}).get("classification", {}).get("cwe-id", [""])[0] if entry.get("info", {}).get("classification", {}).get("cwe-id") else "",
                    attack_type=entry.get("info", {}).get("name", ""),
                    evidence=Evidence(
                        raw_output=line,
                        matched_at=entry.get("matched-at", ""),
                        template=entry.get("template-id", ""),
                    ),
                    root_cause=entry.get("info", {}).get("description", ""),
                    status=FindingStatus.DISCOVERED,
                ))
            except (json.JSONDecodeError, KeyError):
                continue
        return findings
    
    def _generate_remediations(self, finding: Finding) -> list[RemediationAction]:
        """CWE 기반 방어 액션 자동 생성."""
        actions = []
        rem_types = self.CWE_REMEDIATION_MAP.get(finding.cwe_id, [RemediationType.CONFIG])
        
        for rem_type in rem_types:
            match rem_type:
                case RemediationType.WAF_RULE:
                    actions.append(RemediationAction(
                        type=RemediationType.WAF_RULE,
                        description=f"Block {finding.attack_type} on {finding.endpoint}",
                        target_system="WAF",
                        waf_rule=self._generate_waf_rule(finding),
                        automatable=True,
                        requires_approval=False,
                        risk_of_disruption="low",
                    ))
                case RemediationType.CODE_PATCH:
                    actions.append(RemediationAction(
                        type=RemediationType.CODE_PATCH,
                        description=f"Fix {finding.cwe_id} in {finding.endpoint}",
                        target_system="application",
                        automatable=True,
                        requires_approval=True,  # 코드 변경은 승인 필요
                        risk_of_disruption="medium",
                    ))
                case RemediationType.CONFIG:
                    actions.append(RemediationAction(
                        type=RemediationType.CONFIG,
                        description=f"Harden config for {finding.target}",
                        target_system="infrastructure",
                        automatable=True,
                        requires_approval=False,
                        risk_of_disruption="low",
                    ))
                case RemediationType.DETECTION:
                    actions.append(RemediationAction(
                        type=RemediationType.DETECTION,
                        description=f"Add detection rule for {finding.attack_type}",
                        target_system="SIEM",
                        detection_rule=self._generate_sigma_rule(finding),
                        automatable=True,
                        requires_approval=False,
                        risk_of_disruption="none",
                    ))
        
        return actions
```

### 2.2 Defense OPPLAN 생성기

```python
# decepticon/feedback/defense_planner.py

class DefensePlanner:
    """Findings에서 Defense OPPLAN 자동 생성."""
    
    async def generate_defense_opplan(
        self, findings: list[Finding], engagement: str
    ) -> DefenseOPPLAN:
        """방어 OPPLAN 생성."""
        objectives = []
        
        for finding in findings:
            for action in finding.remediation_actions:
                objectives.append(DefenseObjective(
                    id=f"DEF-{len(objectives)+1:03d}",
                    title=action.description,
                    source_finding=finding.id,
                    finding_severity=finding.severity,
                    type=action.type,
                    target_system=action.target_system,
                    action=action,
                    priority=self._calculate_priority(finding, action),
                    approval=self._determine_approval(finding, action),
                    status="pending",
                ))
        
        # 우선순위 정렬: 자동+즉시 > 자동+예약 > 승인 필요
        objectives.sort(key=lambda o: (
            0 if o.approval == "auto" else 1,
            {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(o.finding_severity, 4),
        ))
        
        return DefenseOPPLAN(
            engagement_name=f"{engagement}-defense",
            source_engagement=engagement,
            objectives=objectives,
        )
    
    def _determine_approval(self, finding: Finding, action: RemediationAction) -> str:
        """승인 방식 결정."""
        if action.risk_of_disruption in ("medium", "high"):
            return "human_required"
        if action.requires_approval:
            return "human_required"
        if finding.severity == "CRITICAL" and action.type == RemediationType.WAF_RULE:
            return "auto"  # CRITICAL WAF는 즉시 자동
        return "auto"
```

## 3. Defensive Agents

### 3.1 기술 스택별 구현

```python
# decepticon/defense/waf_agent.py — WAF 규칙 관리

class WAFAgent:
    """WAF 규칙 자동 관리. ModSecurity / Cloudflare / AWS WAF 지원."""
    
    backends = {
        "modsecurity": ModSecurityBackend,
        "cloudflare": CloudflareBackend,
        "aws_waf": AWSWAFBackend,
    }
    
    async def apply(self, action: RemediationAction, config: DefenseConfig) -> RemediationResult:
        backend = self.backends[config.waf_backend](config)
        
        # 1. 규칙 적용 (monitor 모드 먼저)
        rule_id = await backend.add_rule(
            action.waf_rule,
            mode="monitor",  # 먼저 모니터링
            tag=f"decepticon-{action.finding_id}",
        )
        
        # 2. 카나리아 테스트 (5분 대기 후 정상 트래픽 확인)
        await asyncio.sleep(300)
        false_positives = await backend.check_false_positives(rule_id)
        
        if false_positives > 0:
            await backend.remove_rule(rule_id)
            return RemediationResult(
                success=False,
                reason=f"{false_positives} false positives detected, rule removed",
            )
        
        # 3. block 모드로 전환
        await backend.update_rule(rule_id, mode="block")
        
        return RemediationResult(success=True, rule_id=rule_id)

# --- WAF 백엔드 구현 ---

class ModSecurityBackend:
    """ModSecurity CRS 규칙 관리. SSH 또는 API 경유."""
    
    async def add_rule(self, rule: str, mode: str, tag: str):
        rule_file = f"/etc/modsecurity/rules/{tag}.conf"
        rule_content = rule.replace("deny", "pass" if mode == "monitor" else "deny")
        # SSH로 파일 쓰기 + nginx reload
        await self.ssh.write_file(rule_file, rule_content)
        await self.ssh.exec("nginx -s reload")
        return tag

class CloudflareBackend:
    """Cloudflare WAF API."""
    
    async def add_rule(self, rule: str, mode: str, tag: str):
        # Cloudflare API v4
        resp = await self.client.post(
            f"/zones/{self.zone_id}/firewall/rules",
            json={
                "filter": {"expression": rule},
                "action": "log" if mode == "monitor" else "block",
                "description": tag,
            }
        )
        return resp.json()["result"]["id"]
```

```python
# decepticon/defense/patch_agent.py — 코드 패치 생성

class PatchAgent:
    """LLM 기반 코드 패치 자동 생성 + PR."""
    
    async def apply(self, action: RemediationAction, config: DefenseConfig) -> RemediationResult:
        # 1. 취약점 컨텍스트 로드
        vuln_context = await self._load_vulnerability_context(action)
        
        # 2. LLM에게 패치 생성 요청 (coding agent 스킬 활용)
        patch_prompt = f"""
        Fix the following vulnerability:
        - CWE: {action.finding.cwe_id}
        - File: {action.finding.endpoint}
        - Root cause: {action.finding.root_cause}
        - Evidence: {action.finding.evidence.raw_output[:500]}
        
        Generate a minimal, focused patch that:
        1. Fixes the root cause (not just a WAF bypass)
        2. Adds input validation where needed
        3. Does NOT break existing functionality
        4. Includes a test case for the fix
        """
        
        # Claude Code를 ACP로 스폰 (OpenClaw 패턴)
        result = await self.spawn_coding_agent(
            prompt=patch_prompt,
            workdir=config.repo_path,
            branch=f"decepticon/fix-{action.finding.id}",
        )
        
        # 3. PR 생성
        if result.success:
            pr = await self.github.create_pr(
                title=f"[Decepticon] Fix {action.finding.cwe_id}: {action.description}",
                body=self._format_pr_body(action, result),
                branch=f"decepticon/fix-{action.finding.id}",
                base="main",
                labels=["security", "decepticon-auto"],
            )
            return RemediationResult(success=True, pr_url=pr.html_url)
        
        return RemediationResult(success=False, reason=result.error)
```

```python
# decepticon/defense/detection_agent.py — 탐지 규칙 생성

class DetectionAgent:
    """Sigma 규칙 자동 생성 + SIEM 배포."""
    
    async def apply(self, action: RemediationAction, config: DefenseConfig) -> RemediationResult:
        # 1. Sigma 규칙 생성
        sigma_rule = self._generate_sigma(action)
        
        # 2. SIEM에 배포
        match config.siem_type:
            case "splunk":
                spl = sigma_to_spl(sigma_rule)
                await self.splunk_api.create_saved_search(
                    name=f"Decepticon: {action.description}",
                    search=spl,
                    alert_type="real-time",
                )
            case "elastic":
                eql = sigma_to_eql(sigma_rule)
                await self.elastic_api.create_detection_rule(
                    name=f"Decepticon: {action.description}",
                    query=eql,
                    severity=action.finding.severity.lower(),
                )
        
        return RemediationResult(success=True)
    
    def _generate_sigma(self, action: RemediationAction) -> dict:
        """CWE 기반 Sigma 규칙 템플릿 생성."""
        return {
            "title": f"Decepticon Detection: {action.description}",
            "status": "experimental",
            "description": f"Detects {action.finding.attack_type} targeting {action.finding.target}",
            "logsource": self._determine_logsource(action),
            "detection": self._build_detection_logic(action),
            "level": action.finding.severity.lower(),
            "tags": [f"attack.{action.finding.mitre_id}"] if action.finding.mitre_id else [],
        }
```

## 4. Knowledge Graph Integration

### 4.1 공격-방어 KG 스키마

```python
# decepticon/kg/attack_defense_schema.py

class AttackDefenseKG:
    """공격-방어 사이클을 위한 Neo4j KG 확장."""
    
    SCHEMA = """
    // Node types
    CREATE CONSTRAINT IF NOT EXISTS FOR (t:Target) REQUIRE t.id IS UNIQUE;
    CREATE CONSTRAINT IF NOT EXISTS FOR (v:Vulnerability) REQUIRE v.id IS UNIQUE;
    CREATE CONSTRAINT IF NOT EXISTS FOR (f:Finding) REQUIRE f.id IS UNIQUE;
    CREATE CONSTRAINT IF NOT EXISTS FOR (r:Remediation) REQUIRE r.id IS UNIQUE;
    CREATE CONSTRAINT IF NOT EXISTS FOR (a:Attack) REQUIRE a.id IS UNIQUE;
    
    // Indexes
    CREATE INDEX IF NOT EXISTS FOR (f:Finding) ON (f.severity);
    CREATE INDEX IF NOT EXISTS FOR (f:Finding) ON (f.status);
    CREATE INDEX IF NOT EXISTS FOR (r:Remediation) ON (r.status);
    """
    
    async def store_finding(self, finding: Finding):
        """Finding을 KG에 저장하고 관계 생성."""
        await self.run("""
            MERGE (t:Target {id: $target})
            MERGE (f:Finding {id: $finding_id})
            SET f += $finding_props
            MERGE (f)-[:FOUND_ON]->(t)
            
            WITH f
            OPTIONAL MATCH (v:Vulnerability {cwe: $cwe_id})
            MERGE (v2:Vulnerability {cwe: $cwe_id})
            MERGE (f)-[:INSTANCE_OF]->(v2)
        """, {
            "target": finding.target,
            "finding_id": finding.id,
            "finding_props": finding.to_kg_props(),
            "cwe_id": finding.cwe_id,
        })
    
    async def store_remediation(self, remediation: Remediation, finding_id: str):
        """Remediation을 KG에 저장."""
        await self.run("""
            MATCH (f:Finding {id: $finding_id})
            MERGE (r:Remediation {id: $rem_id})
            SET r += $rem_props
            MERGE (f)-[:REMEDIATED_BY]->(r)
        """, {
            "finding_id": finding_id,
            "rem_id": remediation.id,
            "rem_props": remediation.to_kg_props(),
        })
    
    async def mark_immune(self, finding_id: str):
        """Finding을 면역 상태로 표시."""
        await self.run("""
            MATCH (f:Finding {id: $finding_id})-[:FOUND_ON]->(t:Target)
            MATCH (f)-[:INSTANCE_OF]->(v:Vulnerability)
            SET f.status = 'immune'
            MERGE (t)-[:IMMUNE_TO]->(v)
        """, {"finding_id": finding_id})
    
    async def query_unimmune(self, engagement: str) -> list[dict]:
        """면역되지 않은 취약점 조회."""
        return await self.run("""
            MATCH (f:Finding)-[:FOUND_ON]->(t:Target)
            WHERE f.engagement = $engagement
            AND f.status <> 'immune'
            RETURN f.id, f.title, f.severity, t.id as target
            ORDER BY 
                CASE f.severity 
                    WHEN 'CRITICAL' THEN 0 
                    WHEN 'HIGH' THEN 1 
                    WHEN 'MEDIUM' THEN 2 
                    ELSE 3 
                END
        """, {"engagement": engagement})
    
    async def convergence_stats(self, engagement: str) -> dict:
        """수렴 통계."""
        return await self.run("""
            MATCH (f:Finding)
            WHERE f.engagement = $engagement
            RETURN 
                count(f) as total,
                count(CASE WHEN f.status = 'immune' THEN 1 END) as immune,
                count(CASE WHEN f.status = 'discovered' THEN 1 END) as discovered,
                count(CASE WHEN f.status = 'remediating' THEN 1 END) as remediating,
                f.severity as severity
            GROUP BY f.severity
        """, {"engagement": engagement})
```

## 5. OPSEC Hook Engine

### 5.1 구현

```python
# decepticon/gateway/opsec_hooks.py

class OPSECHookEngine:
    """모든 에이전트 액션에 OPSEC 가드레일 적용.
    OpenClaw before_tool_call/after_tool_call 패턴."""
    
    def __init__(self, config: OPSECConfig):
        self.config = config
        self.hooks_before: list[BeforeExecuteHook] = [
            ROEScopeCheck(),
            TimeWindowCheck(),
            RateLimitCheck(),
            NoisyCommandCheck(),
        ]
        self.hooks_after: list[AfterExecuteHook] = [
            EvidenceCapture(),
            KGUpdater(),
            FindingClassifier(),
            DeconflictionCheck(),
        ]
    
    async def before_execute(self, objective: Objective):
        """실행 전 모든 OPSEC 훅 실행. 하나라도 실패 시 중단."""
        for hook in self.hooks_before:
            result = await hook.check(objective, self.config)
            if result.blocked:
                raise OPSECViolation(
                    hook=hook.__class__.__name__,
                    reason=result.reason,
                    objective=objective.id,
                )
    
    async def after_execute(self, objective: Objective, result: dict):
        """실행 후 모든 OPSEC 훅 실행. 실패해도 계속."""
        for hook in self.hooks_after:
            try:
                await hook.process(objective, result, self.config)
            except Exception as e:
                log.warning(f"After-execute hook {hook.__class__.__name__} failed: {e}")

class ROEScopeCheck(BeforeExecuteHook):
    """RoE 범위 검증."""
    async def check(self, objective, config) -> HookResult:
        roe = await load_roe(config.roe_path)
        target = objective.metadata.get("target", "")
        
        if not roe.is_in_scope(target):
            return HookResult(blocked=True, reason=f"Target {target} not in RoE scope")
        
        if target in roe.exclusions:
            return HookResult(blocked=True, reason=f"Target {target} explicitly excluded")
        
        return HookResult(blocked=False)

class EvidenceCapture(AfterExecuteHook):
    """증거 자동 캡처."""
    async def process(self, objective, result, config):
        evidence_dir = Path(config.workspace) / "evidence" / objective.id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        
        # 도구 출력 저장
        for i, output in enumerate(result.get("tool_outputs", [])):
            (evidence_dir / f"tool_{i}_{output.tool}.txt").write_text(output.result)
        
        # 타임스탬프 + 해시
        manifest = {
            "objective_id": objective.id,
            "captured_at": datetime.now().isoformat(),
            "files": [],
        }
        for f in evidence_dir.iterdir():
            manifest["files"].append({
                "name": f.name,
                "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                "size": f.stat().st_size,
            })
        
        (evidence_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
```

## 6. 기존 Decepticon 통합 포인트

### 6.1 변경이 필요한 기존 파일

```
최소 변경 원칙: 기존 코드를 가능한 유지하고, 새 모듈 추가

기존 파일 (수정):
  decepticon/__main__.py        → RedGate 시작 옵션 추가
  decepticon/core/config.py     → RedGateConfig 통합
  decepticon/core/schemas.py    → Finding, Remediation 스키마 추가

새 파일 (추가):
  decepticon/gateway/           → RedGate 전체 (새 패키지)
  decepticon/channels/          → Discord 통합 (새 패키지)
  decepticon/feedback/          → 피드백 파이프라인 (새 패키지)
  decepticon/defense/           → 방어형 에이전트 (새 패키지)

기존 파일 (유지):
  decepticon/agents/            → 공격형 에이전트 (변경 없음)
  decepticon/backends/          → Docker sandbox (변경 없음)
  decepticon/middleware/        → OPPLAN middleware (변경 없음)
  decepticon/llm/               → LLM factory (변경 없음)
```

### 6.2 기존 에이전트와의 연결

```python
# decepticon/gateway/agent_factory.py

class AgentFactory:
    """기존 Decepticon 에이전트를 AgentPool에서 사용할 수 있도록 래핑."""
    
    def create(self, agent_type: str, sandbox, roe, workspace) -> Agent:
        """기존 create_agent()를 호출하되, RedGate 컨텍스트를 주입."""
        
        # 기존 에이전트 미들웨어 스택 재사용
        from decepticon.agents.recon import create_recon_agent
        from decepticon.agents.exploit import create_exploit_agent
        from decepticon.agents.postexploit import create_postexploit_agent
        
        creators = {
            "recon": create_recon_agent,
            "exploit": create_exploit_agent,
            "postexploit": create_postexploit_agent,
        }
        
        creator = creators[agent_type]
        return creator(
            sandbox=sandbox,
            roe=roe,
            workspace=workspace,
            # 기존 미들웨어 스택 그대로 사용:
            # SafeCommand → Skills → Filesystem → SubAgent → OPPLAN →
            # ModelFallback → Summarization → PromptCaching → PatchToolCalls
        )
```

## 7. 구현 순서

```
Phase 1 (Week 1-2): Agent Pool
  ├── SandboxPool (Docker 풀 관리)
  ├── AgentPool (병렬 스폰)
  ├── AgentFactory (기존 에이전트 래핑)
  └── 테스트: 3개 병렬 에이전트 실행

Phase 2 (Week 3-4): Feedback Pipeline
  ├── FindingExtractor (nuclei, nmap, sqlmap 파서)
  ├── DefensePlanner (방어 OPPLAN 생성)
  ├── KG 스키마 확장 (Finding, Remediation)
  └── 테스트: 에이전트 결과 → Finding → KG

Phase 3 (Week 5-6): Defensive Agents
  ├── WAFAgent (ModSecurity backend)
  ├── DetectionAgent (Sigma 규칙 생성)
  ├── ConfigAgent (설정 강화)
  └── 테스트: Finding → 방어 적용 → 검증

Phase 4 (Week 7-8): OPSEC + Integration
  ├── OPSECHookEngine (RoE, 시간, 속도)
  ├── EvidenceCapture (자동 증거)
  ├── 기존 에이전트 통합 테스트
  └── E2E 테스트: 공격 → 발견 → 방어 → 검증
```
