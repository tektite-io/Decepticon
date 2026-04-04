---
name: reporting
description: "Recon output formatting — report structure, CVSS scoring, MITRE ATT&CK mapping, finding prioritization, Markdown/JSON output, handoff checklists."
allowed-tools: Read Write
metadata:
  subdomain: reporting
  when_to_use: "generate report, write report, summarize findings, CVSS score, prioritize findings, recon report, final report, handoff"
  tags: report, cvss, findings, mitre-mapping, handoff
  mitre_attack:
---

# Reconnaissance Reporting Knowledge Base

Effective reconnaissance is only as valuable as the intelligence it communicates. This skill defines how to structure, prioritize, and present findings for actionable handoff to the next engagement phase.

## 1. Report Structure

Every recon engagement should produce a structured report with these sections:

### Executive Summary
A 2-3 sentence overview of what was found, the overall attack surface size, and the most critical findings.

### Target Overview
| Field | Value |
|-------|-------|
| Primary Domain | example.com |
| Scope | *.example.com, 10.0.0.0/24 |
| Engagement Type | External Recon |
| Recon Duration | Passive: X min, Active: Y min |

## 2. Finding Categories

### A. Domain & Subdomain Inventory
```markdown
| Subdomain | IP Address | Status | Notes |
|-----------|-----------|--------|-------|
| www.example.com | 93.184.216.34 | Active | Main site, Cloudflare CDN |
| api.example.com | 10.0.1.50 | Active | REST API, no WAF detected |
| dev.example.com | 10.0.1.51 | Active | Development server, potential target |
| old.example.com | — | NXDOMAIN | Decommissioned |
| staging.example.com | CNAME → *.herokuapp.com | Dangling | Subdomain takeover candidate |
```

### B. DNS & Infrastructure Map
```markdown
| Record Type | Value | Analysis |
|-------------|-------|----------|
| A | 93.184.216.34 | Primary web server |
| MX | aspmx.l.google.com (pri 10) | Google Workspace email |
| NS | ns1.cloudflare.com | Cloudflare DNS hosting |
| TXT (SPF) | v=spf1 include:_spf.google.com ~all | Soft fail SPF |
| TXT (DMARC) | v=DMARC1; p=none | DMARC not enforced |
| CAA | 0 issue "letsencrypt.org" | Only Let's Encrypt can issue certs |
```

### C. Open Ports & Services
```markdown
| IP | Port | Protocol | Service | Version | Risk Notes |
|----|------|----------|---------|---------|------------|
| 10.0.1.50 | 22 | TCP | SSH | OpenSSH 8.9p1 | Current version |
| 10.0.1.50 | 80 | TCP | HTTP | nginx 1.18.0 | Outdated (CVE potential) |
| 10.0.1.50 | 443 | TCP | HTTPS | nginx 1.18.0 | TLS 1.2, missing HSTS |
| 10.0.1.50 | 3306 | TCP | MySQL | 5.7.42 | Exposed database port |
| 10.0.1.51 | 8080 | TCP | HTTP | Apache Tomcat 9.0.65 | Dev server, default page |
```

### D. Technology Stack
```markdown
| Layer | Technology | Evidence |
|-------|-----------|----------|
| CDN | Cloudflare | CF-RAY header, NS records |
| Web Server | nginx 1.18.0 | Server header |
| Backend | PHP 8.1 | X-Powered-By header |
| CMS | WordPress 6.x | /wp-content/ paths |
| Database | MySQL 5.7 | Port 3306 open, banner |
| Email | Google Workspace | MX records |
| DNS | Cloudflare | NS records |
```

### E. Vulnerability Scan Results
```markdown
| Source | Target | Finding | Severity | Template/CVE |
|--------|--------|---------|----------|--------------|
| nuclei | api.example.com | Exposed .env file | CRITICAL | exposure-env |
| nuclei | dev.example.com | Git config disclosure | HIGH | git-config |
| nikto | www.example.com | X-Frame-Options missing | MEDIUM | — |
| nmap | 10.0.1.50:443 | TLS 1.0 supported | MEDIUM | ssl-enum-ciphers |
```

## 3. CVSS Scoring

### CVSS 3.1 Quick Reference
Use CVSS 3.1 base scores for consistent severity rating:

| Score Range | Severity | Color |
|------------|----------|-------|
| 9.0 – 10.0 | Critical | Red |
| 7.0 – 8.9 | High | Orange |
| 4.0 – 6.9 | Medium | Yellow |
| 0.1 – 3.9 | Low | Blue |
| 0.0 | None | Gray |

### Common Recon Finding CVSS Scores
| Finding | CVSS 3.1 | Vector |
|---------|----------|--------|
| Exposed database port (MySQL/Postgres) | 9.8 | AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H |
| Subdomain takeover | 8.6 | AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:N/A:N |
| .env file exposure | 7.5 | AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N |
| Git config disclosure | 7.5 | AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N |
| Directory listing enabled | 5.3 | AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N |
| Missing security headers | 4.3 | AV:N/AC:L/PR:N/UI:R/S:U/C:N/I:L/A:N |
| Information disclosure (version) | 5.3 | AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N |
| DMARC not enforced | 3.7 | AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:L/A:N |

### CVSS 4.0 Reference
CVSS 4.0 replaces the Scope metric with supplemental metrics. Use when client requires.

| CVSS 4.0 Score | Severity | Qualitative |
|----------------|----------|-------------|
| 9.0 – 10.0 | Critical | Immediate remediation required |
| 7.0 – 8.9 | High | Remediate within days |
| 4.0 – 6.9 | Medium | Remediate within weeks |
| 0.1 – 3.9 | Low | Remediate within quarter |

CVSS 4.0 key changes:
- **Attack Requirements (AT)**: Replaces part of Attack Complexity — conditions beyond attacker control
- **No more Scope (S)**: Replaced by Provider Urgency (U) supplemental metric
- **Automatable (AU)**: Can the attack be automated at scale?
- **Recovery (R)**: How quickly does the system recover?

When dual-reporting:
```markdown
- **CVSS 3.1**: 9.8 (AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H)
- **CVSS 4.0**: 9.3 (AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N)
```

## 4. MITRE ATT&CK Mapping

### Reconnaissance Tactics (TA0043)
Map each finding to relevant MITRE ATT&CK techniques:

| Technique ID | Name | Recon Activity |
|-------------|------|---------------|
| T1595.001 | Active Scanning: IP Blocks | nmap port scanning |
| T1595.002 | Active Scanning: Vulnerability Scanning | nuclei, nikto scans |
| T1595.003 | Active Scanning: Wordlist Scanning | ffuf, gobuster |
| T1592.001 | Gather Victim Host Info: Hardware | OS fingerprinting (-O) |
| T1592.002 | Gather Victim Host Info: Software | Service version detection (-sV) |
| T1593.001 | Search Open Websites: Social Media | OSINT gathering |
| T1593.002 | Search Open Websites: Search Engines | Google dorking |
| T1596.001 | Search Open Technical Databases: DNS/Passive DNS | dig, subfinder, amass |
| T1596.002 | Search Open Technical Databases: WHOIS | whois lookups |
| T1596.003 | Search Open Technical Databases: Digital Certificates | crt.sh CT log queries |

### Report Mapping Format
```markdown
### Finding: Exposed MySQL on api.example.com:3306

- **CVSS 3.1**: 9.8 (Critical)
- **MITRE ATT&CK**: T1595.001 (Active Scanning: IP Blocks)
- **Evidence**: nmap -sV shows MySQL 5.7.42 open to internet
- **Risk**: Direct database access if credentials are weak/default
- **Recommendation**: Immediate firewall rule to restrict access
```

## 5. Finding Prioritization

### Priority Levels

| Priority | Criteria | Example |
|----------|----------|---------|
| **CRITICAL** | Immediate exploitation potential, CVSS ≥ 9.0 | Exposed database, default creds, subdomain takeover |
| **HIGH** | Known CVE or significant misconfiguration, CVSS 7.0-8.9 | Outdated service with public exploit, missing auth |
| **MEDIUM** | Information disclosure or weak configuration, CVSS 4.0-6.9 | Verbose error pages, missing security headers |
| **LOW** | Informational or hardening recommendation, CVSS < 4.0 | DMARC not enforced, older TLS ciphers supported |

### Priority Assessment Format
```markdown
## Critical Findings

### 1. [CRITICAL] Exposed MySQL on api.example.com:3306
- **CVSS 3.1**: 9.8 (AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H)
- **MITRE ATT&CK**: T1595.001
- **Evidence**: nmap -sV shows MySQL 5.7.42 open to internet
- **Risk**: Direct database access if credentials are weak/default
- **Recommendation**: Immediate firewall rule to restrict access

## High Findings

### 2. [HIGH] Dangling CNAME — staging.example.com
- **CVSS 3.1**: 8.6 (AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:N/A:N)
- **MITRE ATT&CK**: T1596.001
- **Evidence**: CNAME points to deprovisioned Heroku app
- **Risk**: Subdomain takeover → phishing, cookie theft
- **Recommendation**: Remove DNS record or reclaim the Heroku app
```

## 6. Attack Chain Analysis

### Identifying Exploit Chains
Individual findings combine into attack chains. Document these explicitly — they
represent the real-world risk better than isolated findings.

```markdown
## Attack Chain: Unauthenticated Database Access

**Chain**: Subdomain discovery → Exposed MySQL → Credential extraction
**Combined Risk**: CRITICAL

1. Passive recon discovered `db.example.com` via CT logs
2. Active scan confirmed MySQL 5.7.42 on port 3306 (internet-facing)
3. No authentication required for `root` user (empty password)
4. Database contains PII for ~50,000 users

**Impact**: Full database compromise without any credentials
**Remediation**: Firewall MySQL port, set root password, audit access logs
```

### Chain Severity Escalation
When findings chain together, the combined severity may exceed individual scores:

| Individual Findings | Severity Alone | Chained Severity |
|-------------------|---------------|-----------------|
| Directory listing + .env exposure | Medium + High | CRITICAL (credentials leaked) |
| Subdomain takeover + cookie scope | High + Medium | CRITICAL (session hijack) |
| SSRF + cloud metadata | Medium + N/A | CRITICAL (IAM credential theft) |
| Weak TLS + HSTS missing | Low + Low | Medium (downgrade attack viable) |

## 7. JSON Output Format

For machine-readable output or integration with other tools:
```json
{
  "target": "example.com",
  "timestamp": "2026-03-13T14:30:00Z",
  "scope": ["*.example.com", "10.0.1.0/24"],
  "mitre_tactics": ["TA0043"],
  "findings": {
    "subdomains": [
      {"name": "api.example.com", "ip": "10.0.1.50", "status": "active"},
      {"name": "staging.example.com", "cname": "*.herokuapp.com", "status": "dangling"}
    ],
    "services": [
      {
        "ip": "10.0.1.50",
        "port": 3306,
        "service": "mysql",
        "version": "5.7.42",
        "priority": "critical",
        "cvss": 9.8,
        "cvss_vector": "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        "mitre": "T1595.001"
      }
    ],
    "vulnerabilities": [
      {
        "target": "api.example.com",
        "finding": "Exposed .env file",
        "source": "nuclei",
        "severity": "critical",
        "cvss": 7.5,
        "template": "exposure-env"
      }
    ],
    "priorities": {
      "critical": 1,
      "high": 1,
      "medium": 2,
      "low": 3
    }
  }
}
```

## 7. File Management

### Naming Convention
```
./
├── recon_<target>_passive.txt      # Passive recon raw output
├── recon_<target>_subdomains.txt   # Subdomain list
├── httpx_<target>.txt              # Live host probing results
├── nmap_<target>_<scan_type>.txt   # Nmap scan results
├── nmap_<target>_<scan_type>.xml   # Nmap XML for tool import
├── ffuf_<target>.json              # Web fuzzing results
├── nuclei_<target>.txt             # Vulnerability scan results
└── report_<target>_final.md        # Final consolidated report
```

### Result Persistence
- Always save scan results with `-oN` (nmap), `-o` (subfinder/nuclei/httpx), or `-of json` (ffuf)
- Large outputs should be written to files, not displayed inline
- Keep raw data — the final report synthesizes, but raw data enables re-analysis

## 8. OPPLAN Feedback Loop

After generating the report, update the OPPLAN to reflect actual findings:

### Update Completed Objectives
For each recon objective in `opplan.json`:
- Set `"status": "completed"` for finished objectives
- Add actual findings summary to a `"results"` field
- Note any objectives that were blocked or partially completed

### Create Follow-Up Objectives
If the report reveals new targets or attack paths not in the original OPPLAN:
1. Create new objectives following the `OBJ-{PHASE}-{NUMBER}` convention
2. Assign priorities based on finding severity (CRITICAL findings → highest priority)
3. Ensure new objectives have scope check, OPSEC check, and output persistence criteria
4. Use `opplan-converter` skill's `references/objective-rules.md` for validation

### Report → OPPLAN Mapping
```json
{
  "report_finding": "Exposed MySQL on api.example.com:3306 (CRITICAL, CVSS 9.8)",
  "opplan_update": {
    "completed_objective": "OBJ-REC-006 (port scan discovered the open port)",
    "new_objective": "OBJ-EXP-001 (test MySQL default credentials — if exploitation phase authorized)"
  }
}
```

## 9. Handoff Checklist

Before concluding reconnaissance and handing off to the exploitation phase:

- [ ] All subdomains enumerated and resolved
- [ ] DNS infrastructure fully mapped
- [ ] All in-scope IPs port-scanned with service versions
- [ ] Technology stack identified for key assets
- [ ] Vulnerability scan (nuclei) run on all live web targets
- [ ] Findings scored with CVSS 3.1
- [ ] Findings mapped to MITRE ATT&CK techniques
- [ ] Findings prioritized by exploitability
- [ ] Final report saved to `report_<target>_final.md`
- [ ] JSON output saved for tool integration
- [ ] Raw scan data preserved in the engagement directory
- [ ] `opplan.json` updated with completed objectives and new findings
- [ ] New follow-up objectives created for next phase (if authorized)
