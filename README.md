# lee-ctf

## WMux browser session with Chrome DevTools MCP

To attach Chrome DevTools MCP to the browser session already open in WMux,
merge the `chrome-devtools` table from
[`.codex/config.example.toml`](.codex/config.example.toml) into the
user-specific `%USERPROFILE%\.codex\config.toml`. Keep the setting out of the
repository's real configuration and never commit user paths, tokens, or other
local settings.

The required server argument is
`--browser-url=http://127.0.0.1:9222`. Do not use `--isolated` or
`--executablePath`: those options make the MCP server use a separate browser
instead of WMux's CDP proxy. Verify the local proxy without changing browser
state:

```powershell
curl.exe --silent --show-error --max-time 5 http://127.0.0.1:9222/json/version
codex mcp get chrome-devtools --json
```

CDP grants broad control over the attached browser session. Keep the proxy
bound to loopback, do not expose port 9222 through a firewall, tunnel, or port
forward, and only run a reviewed MCP server. Restart Codex (or reconnect the
MCP server) after changing the user configuration.

Windows와 Kali WSL에서 승인된 CTF·모의해킹·보안 연구를 재현 가능하게 수행하기 위한 Codex 작업 공간입니다. 원본 입력, 조사 작업, 증거, 재현 가능한 solver를 분리하고, Codex는 CTF 전용 skill과 짧은 프로젝트 지침을 사용합니다.

## 빠른 시작

```powershell
git clone https://github.com/daejaeLee/lee-ctf.git
Set-Location .\lee-ctf

.\ctf.ps1 doctor --project-only
python .\scripts\check_skill_snapshot.py
.\scripts\codex-ctf.ps1
```

일반 `codex` 실행도 이 저장소 안에서는 `.codex/config.toml`을 읽어 같은 skill-context 및 plugin 정책을 적용합니다. wrapper는 이전 실행 방식과 호환되는 편의 진입점입니다.

## Architecture

```text
AGENTS.md ──> category router ──> ctf-* skill ──> challenge work
     │                                      │
     │                                      ├─ notes.md / evidence/ / solve/ / artifacts
     │                                      │             (authoritative state)
     │                                      └─ Terra / Luna / Sol model routing
     │
claude-mem ──> cross-session recall only ──> current artifact verification

ECC plugin ──> disabled for this project
              shared/ctf-ecc-on-demand.md (read only when relevant)
```

`AGENTS.md`는 challenge category를 분류하고 적절한 `ctf-*` skill을 고르는 router입니다. `notes.md`, `evidence/`, `solve/`, `input/`, `output/`, 실제 source/binary/artifact가 active challenge의 권위 있는 상태입니다. claude-mem은 과거 작업을 다시 찾는 보조 계층이며 기억한 결론은 반드시 현재 artifact로 검증합니다.

## 디렉터리 구조

```text
.agents/skills/  vendored CTF skills (직접 수정 금지)
.codex/          프로젝트 전용 Codex 설정
.ctf/            category-to-skill routing 및 workspace metadata
c/               c/<event>/<category>/<slug> challenge directories
shared/          on-demand guidance와 재사용 helper
scripts/         PowerShell/WSL 설치·검증·Codex wrapper
templates/       새 challenge 템플릿
docs/examples/   사용자 전역 설정에 복사할 안전한 예제
ctf.ps1          PowerShell 5.1 호환 프로젝트 CLI
```

각 challenge는 `challenge.json`, local `AGENTS.md`, `README.md`, immutable `input/`, disposable `work/`, reproducible `solve/`, generated `output/`, selected `evidence/`, `notes.md`, redacted `writeup.md`를 사용합니다. `input/`은 수정하지 않고, live flag와 credential은 `.local/`에만 둡니다.

## 요구 사항

| 구성 요소 | 용도 | 확인 명령 |
| --- | --- | --- |
| Git for Windows | clone, history | `git --version` |
| PowerShell 5.1+ | host scripts | `$PSVersionTable.PSVersion` |
| Python 3.10+ | project checks and helpers | `python --version` |
| Node.js 20.12+ | Codex 및 claude-mem runtime | `node --version` |
| Codex CLI | coding agent | `codex --version` |
| WSL + Kali (`kali-linux`) | pwn/reverse/forensics/malware tools | `wsl.exe --list --verbose` |
| Bun 1.0+ | claude-mem bundled runner | `bun --version` |
| uv (선택) | 일부 Python workflow | `uv --version` |

현재 claude-mem 13.24.1 manifest는 Node `>=20.12.0`, Bun `>=1.0.0`을 선언합니다. `uv`는 plugin 설치 자체의 필수 항목이 아니며 challenge 또는 별도 Python 작업에서만 필요할 수 있습니다.

Kali 준비와 검증:

```powershell
.\scripts\Install-CtfWsl.ps1 -Distribution kali-linux
.\ctf.ps1 doctor --wsl-tools
```

알 수 없는 malware sample은 Windows host에서 실행하지 말고 격리된 Kali/VM에서만 다룹니다.

## Codex CLI setup

`.codex/config.toml`은 이 repository에서만 다음을 적용합니다.

- root coordinator: `gpt-5.6-terra` / `medium`
- Multi-Agent V2: enabled
- Luna/low: bounded inventory, `rg`, endpoint/symbol/dependency 목록화
- Terra/medium~high: 일반 분석, PoC, solver, debugging, 편집
- Sol/high: assembly, native crash, obfuscation, 복잡한 chain
- Astra/high: Sol이 결정적 증거를 만들지 못했을 때만 예외적으로 사용
- claude-mem: enabled
- ECC, documents, PDF, spreadsheets, presentations 등 비-CTF plugin: project-local disabled

skill routing은 **무엇을 할지**를, model routing은 **어느 수준의 모델이 할지**를 결정합니다. child를 만들 때 role 이름만 쓰지 말고 `model`과 `reasoning_effort`를 명시합니다. search/inventory child는 `fork_turns="none"`과 최소 task context를 사용합니다.

Codex가 project trust 또는 hook trust를 물으면 먼저 repository 및 plugin source를 검토합니다. claude-mem hook은 설치한 plugin 경로와 command가 예상과 일치할 때에만 trust합니다.

## Context optimization

`Exceeded skills context budget` 경고는 설치·활성화된 많은 plugin 및 skill의 설명이 initial model context 한도를 초과할 때 나타납니다. 이 저장소는 CTF skill을 삭제하지 않습니다. Codex 0.153.4 strict config으로 검증한 다음 설정을 사용합니다.

```toml
[skills]
include_instructions = false
```

이는 skill을 비활성화하지 않습니다. 첫 turn에 전체 `SKILL.md` description catalog를 넣지 않을 뿐이며, `AGENTS.md` routing 또는 명시적 요청으로 필요한 skill은 on-demand로 계속 사용합니다. 현재 구성의 `codex debug prompt-input` 비교는 29,332자에서 14,596자로 감소했고 CTF 및 claude-mem skill description이 initial prompt에서 제거됨을 확인했습니다.

## CTF skills

`.agents/skills/`는 vendored snapshot입니다. 삭제·직접 편집하지 않습니다.

| Skill | 목적 |
| --- | --- |
| `solve-challenge` | category가 불명확한 bundle의 first-pass triage |
| `ctf-web` | HTTP/API/client/template/auth 취약점 |
| `ctf-pwn` | native exploit, ROP, heap/stack/format string |
| `ctf-reverse` | binary/APK/WASM/firmware/obfuscation 분석 |
| `ctf-crypto` | RSA, ECC, cipher, PRNG, number theory |
| `ctf-forensics` | disk, memory, PCAP, logs, stego, metadata |
| `ctf-malware` | malicious behavior, C2, PE/.NET, config extraction |
| `ctf-ai-ml` | LLM/ML attack 및 AI puzzle |
| `ctf-osint` | 의도된 public-source discovery |
| `ctf-misc` | jail, encoding, RF/SDR, hybrid puzzle |
| `ctf-writeup` | 재현 검증 후 redacted handoff |

Native target의 동작이 불명확하면 `ctf-reverse`로 시작하고 exploit primitive가 확인된 뒤 `ctf-pwn`으로 전환합니다. `.ctf/config.json`의 category mapping이 이 경로를 유지합니다.

## claude-mem installation and configuration

프로젝트에서는 `claude-mem@claude-mem-local`을 cross-session recall, 이전 조사·결정 회상, 관련 codebase history 검색, observation/summary에 사용합니다. 다음은 authoritative data가 아닙니다: flag, offset, address, credential, endpoint, exploit result, binary state, HTTP response, artifact hash, PoC correctness. 이들은 현재 `notes.md`, `evidence/`, `solve/`, `input/`, `output/`, source/binary/artifact로 확인합니다.

이 환경에서는 `daejaeLee/claude-mem` fork를 우선 사용합니다. Codex 0.153.4에서 확인한 marketplace 문법은 다음과 같습니다.

```powershell
codex plugin marketplace add daejaeLee/claude-mem --ref main
codex plugin marketplace list --json
codex plugin add claude-mem@thedotmack
codex plugin list --json
```

fork의 현재 marketplace metadata name은 `thedotmack`이므로 위 plugin selector를 사용합니다. 설치 후 `Hooks need review`가 나타나면 `Review hooks`에서 `claude-mem` plugin 경로와 command를 확인하고, 의도한 fork와 일치할 때에만 `Trust all and continue`를 선택합니다. 모르는 plugin 또는 예상과 다른 command는 trust하지 않습니다.

plugin cache에서 수동으로 `npm install`, `bun install`, dependency 파일을 수정하지 마십시오. `node --version`, `bun --version`, `codex plugin list --json`으로 먼저 runtime과 설치 상태를 확인합니다.

### 권장 memory context 크기

claude-mem 13.24.1의 기본 observation 수는 50입니다. CTF에서는 recent memory가 context를 과도하게 쓰지 않도록 [example](docs/examples/claude-mem-settings.json)을 제공합니다.

```powershell
$target = Join-Path $env:USERPROFILE '.claude-mem\settings.json'
New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
Copy-Item .\docs\examples\claude-mem-settings.json $target
```

기존 `settings.json`에 provider, API key, data directory 등 개인 설정이 있으면 위 복사를 사용하지 말고 example의 9개 key만 기존 JSON에 병합합니다. repository는 사용자 전역 설정을 자동으로 overwrite하지 않습니다.

## ECC

ECC는 전역 Codex에서 계속 설치·사용할 수 있습니다. 이 repository의 `.codex/config.toml`과 `scripts/codex-ctf.ps1`은 `ecc@ecc`를 CTF session에서 disabled로 유지합니다. ECC 전체 catalog는 CTF 기본 context에 필요하지 않고 skill budget을 크게 소비하기 때문입니다.

source-audit, parser, Python solver quality, EVM Keccak 등 CTF에 유용한 원칙은 [shared/ctf-ecc-on-demand.md](shared/ctf-ecc-on-demand.md)에 짧게 선별되어 있습니다. 필요한 경우에만 이 파일을 읽습니다.

## Challenge workflow

```powershell
.\ctf.ps1 new --event example-2026 --category web --name baby-sqli
.\ctf.ps1 import c\example-2026\web\baby-sqli C:\path\to\challenge.zip
.\ctf.ps1 verify-input c\example-2026\web\baby-sqli
.\ctf.ps1 triage c\example-2026\web\baby-sqli
.\ctf.ps1 verify c\example-2026\web\baby-sqli --record
```

권장 순서는 input 저장 → Codex CTF session → category 판별 → 적절한 `ctf-*` skill → `notes.md` 갱신 → `evidence/` 선택 → `solve/` solver → reproduction → redacted write-up → session summary입니다.

## New machine setup

```powershell
# 1. Git, PowerShell, Node.js 20.12+, Codex CLI, WSL/Kali를 먼저 설치한다.
git --version
node --version
codex --version
wsl.exe --list --verbose

# 2. repository clone 및 project validation
git clone https://github.com/daejaeLee/lee-ctf.git
Set-Location .\lee-ctf
.\ctf.ps1 doctor --project-only
python .\scripts\check_skill_snapshot.py

# 3. claude-mem fork marketplace와 plugin 설치
codex plugin marketplace add daejaeLee/claude-mem --ref main
codex plugin add claude-mem@thedotmack
codex plugin list --json

# 4. 새 settings file일 때만 example을 그대로 복사한다.
$settings = Join-Path $env:USERPROFILE '.claude-mem\settings.json'
if (-not (Test-Path $settings)) {
  New-Item -ItemType Directory -Force (Split-Path $settings) | Out-Null
  Copy-Item .\docs\examples\claude-mem-settings.json $settings
}

# 5. hook을 검토·신뢰한 뒤 CTF session 시작
.\scripts\codex-ctf.ps1
```

기존 settings file이 있으면 provider credential을 보존하도록 example key만 병합합니다. hook trust 전에는 plugin source와 command를 검토합니다.

## Verification and troubleshooting

| 증상 | 확인 및 조치 |
| --- | --- |
| `codex`를 찾을 수 없음 | `Get-Command codex`; Codex CLI PATH 설치 상태 확인 |
| plugin ID/marketplace mismatch | `codex plugin marketplace list --json`, `codex plugin list --available --json` 후 실제 selector 확인 |
| hooks not trusted | hook review에서 plugin path와 command를 검토한 뒤 의도한 fork만 trust |
| claude-mem hook이 동작하지 않음 | `node --version`, `bun --version`, `codex plugin list --json`, `%USERPROFILE%\.claude-mem\logs\` 확인 |
| Bun 없음 | Bun 1.0+ 설치 후 새 terminal에서 `bun --version`; plugin cache는 수동 편집하지 않음 |
| skill budget 경고 | project root에서 `codex debug prompt-input test`; `[skills] include_instructions = false`와 ECC disable 확인 |
| ECC가 CTF session에 보임 | project root에서 `codex plugin list --json`을 실행해 `ecc@ecc`가 `enabled:false`인지 확인 |
| memory가 너무 큼 | `%USERPROFILE%\.claude-mem\settings.json`의 observation/session/full count를 example 값으로 낮춘 뒤 새 session 시작 |
| execution policy 오류 | 현재 process에서 `Set-ExecutionPolicy -Scope Process Bypass` 후 script 재시도 |

```powershell
git diff --check
.\ctf.ps1 doctor --project-only
python .\scripts\check_skill_snapshot.py
.\scripts\codex-ctf.ps1 --help
codex plugin list --json
codex plugin marketplace list --json
```

## Updating

```powershell
git pull
.\ctf.ps1 doctor --project-only
python .\scripts\check_skill_snapshot.py

# Codex 0.153.4에는 `codex plugin update`가 없다.
codex plugin marketplace upgrade thedotmack
codex plugin list --json
```

marketplace name이 다르면 `codex plugin marketplace list --json`으로 확인한 실제 이름을 사용합니다. update 후 hook source/command가 바뀌었는지 다시 review합니다.

## 안전 및 재현성

- 외부 host, URL, account, port는 challenge metadata 또는 사용자가 제공한 대상에만 연결합니다.
- flag를 제출하거나 third party에 연락하지 않습니다.
- tracked notes/evidence/write-up에 live flag 또는 credential을 기록하지 않습니다.
- `git status`, artifact hash, solver output을 재현 확인에 사용합니다.
