# lee-ctf

승인된 CTF와 보안 연구를 위한 재현 가능한 Codex 작업 공간입니다. 원본
아티팩트는 보존하고, 실험·증거·최종 솔버를 분리하며, 라이브 플래그와
자격 증명은 Git에 저장하지 않습니다.

## 빠른 시작

```powershell
# 프로젝트 및 Kali 도구 상태 확인
.\ctf.ps1 doctor --project-only
.\ctf.ps1 doctor --wsl-tools

# 프로젝트 스킬 무결성 검사
python scripts\check_skill_snapshot.py

# 새 challenge 생성, 원본 가져오기, triage, 재현 검증
.\ctf.ps1 new --event example-2026 --category web --name baby-sqli
.\ctf.ps1 import c\example-2026\web\baby-sqli C:\Downloads\challenge.zip
.\ctf.ps1 verify-input c\example-2026\web\baby-sqli
.\ctf.ps1 triage c\example-2026\web\baby-sqli
.\ctf.ps1 verify c\example-2026\web\baby-sqli --record
```

CTF 전용 Codex 세션은 다음처럼 실행합니다. 이 래퍼는 해당 실행에만
ECC와 문서·프레젠테이션·스프레드시트 등 비CTF 플러그인을 끄며, 전역
Codex 설정이나 설치된 플러그인은 변경하지 않습니다.

```powershell
.\scripts\codex-ctf.ps1
```

## 작업 구조

```text
.agents/skills/  프로젝트 CTF 스킬(벤더 파일: 직접 수정 금지)
.ctf/            스킬 및 워크스페이스 메타데이터
c/               Challenge: c/<event>/<category>/<slug>
shared/          재사용 가능한 helper, payload, 온디맨드 참고 자료
scripts/         검증, 설치, PowerShell/WSL 자동화
templates/       새 challenge에 복사되는 템플릿
ctf.ps1          PowerShell 5.1 호환 진입점
```

각 challenge는 아래 구조를 사용합니다.

```text
challenge.json   기계 판독 메타데이터와 승인된 target 범위
AGENTS.md        challenge-local 규칙
README.md        문제 설명과 빠른 명령
input/           원본 입력(불변)
work/            폐기 가능한 실험
solve/            최종 재현 솔버/익스플로잇
output/           생성 출력
evidence/         추린 증거
notes.md          확인된 사실, 가설, 실패 경로
writeup.md        플래그를 가린 최종 handoff
```

## CTF 스킬 라우팅

| 분야 | 스킬 |
| --- | --- |
| AI / ML | `ctf-ai-ml` |
| Crypto | `ctf-crypto` |
| Forensics | `ctf-forensics` |
| Malware | `ctf-malware` |
| Misc / jail | `ctf-misc` |
| OSINT | `ctf-osint` |
| Pwn | `ctf-pwn` |
| Reverse | `ctf-reverse` |
| Web | `ctf-web` |

분류가 불명확하면 `solve-challenge`를 사용합니다. native 바이너리의
동작이 아직 불명확하면 먼저 `ctf-reverse`를 사용하고, 취약점 원시값이
확인된 뒤에 `ctf-pwn`으로 전환합니다.

### 프로젝트에 적용된 스킬 명세

아래 스킬은 이 저장소의 [`.agents/skills/`](.agents/skills/)에 포함되어
있고, `AGENTS.md` 및 `.ctf/config.json`의 라우팅 대상입니다. 각 스킬은
challenge의 `AGENTS.md` 지침보다 우선하지 않으며, 해당 문제를 분석할 때만
선택적으로 읽습니다.

| 스킬 | 적용 범위 | 주요 역할 |
| --- | --- | --- |
| `solve-challenge` | 분류 전 / 복합 문제 | 입력 보존, 빠른 triage, 분야 분기, 재현 가능한 handoff |
| `ctf-ai-ml` | AI·LLM·ML | 프롬프트 인젝션, 모델 공격, 데이터·추론 분석 |
| `ctf-crypto` | Crypto | 인코딩, 고전·현대 암호, 수론, RSA/ECC, PRNG 분석 |
| `ctf-forensics` | Forensics | 파일·디스크·메모리·로그·PCAP·메타데이터·스테가노그래피 |
| `ctf-malware` | Malware | 악성 행위, C2/config 추출, 언패킹, 난독화·안티분석 |
| `ctf-misc` | Misc / jail | Python·Bash·eval·AST·제한된 builtins 및 언어 레벨 jail |
| `ctf-osint` | OSINT | 공개 출처 기반 인물·좌표·식별자·웹/DNS 조사 |
| `ctf-pwn` | Pwn | BOF, heap/stack, ROP, format string, shellcode, seccomp·native escape |
| `ctf-reverse` | Reverse | ELF/PE/APK·디컴파일·어셈블리·동적 분석·바이너리 동작 파악 |
| `ctf-web` | Web | HTTP, 인증, XSS, SQLi, SSTI, SSRF, 업로드, API·세션 보안 |
| `ctf-writeup` | 검증 후 문서화 | 재현 절차와 증거를 정리하되 플래그 원문은 가림 |

라우팅 원칙은 다음과 같습니다.

- 바이너리의 동작 또는 취약점이 불명확하면 `ctf-reverse`부터 사용합니다.
- 취약점 원시값과 익스플로잇 조건이 확인되면 `ctf-pwn`을 함께 사용합니다.
- 악성 행위 자체가 핵심이면 `ctf-malware`, 증거 재구성이 핵심이면
  `ctf-forensics`를 우선합니다.
- 공개 검색이 의도된 경로일 때만 `ctf-osint`를 사용합니다. 제공된 파일 분석은
  해당 crypto/forensics/malware/reverse 스킬로 처리합니다.
- `ctf-writeup`은 플래그 형식·대상·재현성이 검증된 뒤에만 사용합니다.

`shared/ctf-ecc-on-demand.md`에는 소스 취약점 triage, Python 솔버 품질,
구조화 파싱, EVM Keccak 주의사항 등 선별된 ECC 지침이 있습니다. 필요할
때만 읽어 스킬 context를 작게 유지합니다.

## 환경 구성

이 저장소는 **Windows 호스트 + Kali WSL + Codex CLI** 조합을 기준으로
구성되어 있습니다. 호스트에는 오케스트레이션만 두고, Linux 우선 보안 도구는
Kali 안에 설치해 Windows Python/패키지 환경을 오염시키지 않습니다.

| 구성 요소 | 기준 구성 | 역할 |
| --- | --- | --- |
| 호스트 OS | Windows | 파일 관리, Codex 실행, PowerShell 오케스트레이션 |
| 셸 | Windows PowerShell 5.1 | `ctf.ps1`, 설치·검증 스크립트 실행 |
| 호스트 Python | Python 3.10 이상 | challenge 생성, 메타데이터 처리, 검증 CLI |
| Linux 환경 | WSL 배포판 `kali-linux` | pwn, reverse, forensics, malware 및 Linux 전용 도구 |
| Codex | Codex CLI 0.153.0에서 검증 | 프로젝트 지침·CTF 스킬·브라우저 기반 웹 흐름 |
| Git | Git for Windows | 재현 가능한 프로젝트 상태와 솔버 관리 |

프로젝트의 실제 기본값은 [`.ctf/config.json`](.ctf/config.json)에 있습니다.
challenge 루트는 `c/`, 기본 WSL 배포판은 `kali-linux`, 카테고리별 라우팅은
`ctf-ai-ml`, `ctf-crypto`, `ctf-forensics`, `ctf-malware`, `ctf-misc`,
`ctf-osint`, `ctf-pwn`, `ctf-reverse`, `ctf-web`입니다.

### 처음 다른 환경에서 준비하기

```powershell
# 1) 저장소를 받은 뒤 호스트 요구 사항을 먼저 확인합니다.
git clone https://github.com/<owner>/lee-ctf.git
Set-Location .\lee-ctf
.\ctf.ps1 doctor --project-only

# 2) WSL에 kali-linux가 없다면 먼저 WSL/Kali를 설치한 뒤 재실행합니다.
wsl.exe --list --verbose

# 3) Kali에 프로젝트가 고정한 CTF 도구 기준선을 설치합니다.
.\scripts\Install-CtfWsl.ps1 -Distribution kali-linux

# 4) 설치 결과와 프로젝트 스킬 스냅샷을 검증합니다.
.\ctf.ps1 doctor --wsl-tools
python .\scripts\check_skill_snapshot.py
```

`Install-CtfWsl.ps1`는 Kali에서 Python 가상환경과 빌드 도구를 준비하고,
프로젝트가 관리하는 **58개 항목 CTF 도구 기준선**을 검증합니다. `pwntools`나
SageMath처럼 challenge에 따라 충돌하거나 큰 의존성이 필요한 것은 호스트
Python에 강제 설치하지 않으며, 필요하면 Kali 또는 challenge-local 환경에서
추가합니다. Python 호환성 오버레이는
[`scripts/ctf-python-compat.txt`](scripts/ctf-python-compat.txt)에 고정되어
있습니다.

Kali 안에서 프로젝트 명령을 실행할 때는 Windows 경로를 직접 변환하지 말고
래퍼를 사용합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-CtfWsl.ps1 `
  verify c\example-2026\pwn\example --record
```

### Codex 프로필과 권한 범위

프로젝트 로컬 [`.codex/config.toml`](.codex/config.toml)은 이 저장소에서만
`approval_policy = "never"`, `sandbox_mode = "danger-full-access"`를 사용합니다.
이는 CTF 아티팩트 분석·로컬 스크립트 실행을 중단 없이 수행하기 위한 설정이며,
Codex 전역 설정을 변경하지 않습니다. 신뢰할 수 없는 challenge는 반드시
격리된 Kali/VM에서 다루고, 알려지지 않은 악성 샘플을 Windows 호스트에서
실행하지 마세요.

기본 Codex 실행은 설치된 플러그인을 모두 로드할 수 있습니다. CTF 작업은
다음 래퍼로 시작합니다.

```powershell
.\scripts\codex-ctf.ps1
```

이 래퍼는 **현재 Codex 실행에만** ECC 전체 번들과 documents, pdf,
spreadsheets, presentations, template-creator, sites, computer-use, visualize
플러그인을 비활성화합니다. 프로젝트의 `ctf-*` 스킬과 브라우저 기반 웹 CTF
흐름은 유지합니다. 따라서 skill context budget을 CTF 풀이에 우선 배정하면서도
글로벌 플러그인 설치 상태는 언제든 그대로 복구할 수 있습니다. 필요한 ECC
지침은 [온디맨드 가이드](shared/ctf-ecc-on-demand.md)로 참조합니다.

다른 명령에 인수를 전달할 수도 있습니다.

```powershell
.\scripts\codex-ctf.ps1 exec --ephemeral
```

### 재현성 확인 기준

다른 장비로 옮긴 직후 아래 세 검사가 모두 통과하면 기본 환경이 갖춰진
것입니다.

```powershell
.\ctf.ps1 doctor --project-only  # Python, 프로젝트 구조, 스킬 스냅샷
.\ctf.ps1 doctor --wsl-tools     # kali-linux의 58개 도구 기준선
python .\scripts\check_skill_snapshot.py
```

호스트의 `docker`, `7z`, `jq`, `gdb`, `file`, `socat`, `ncat` 등은 challenge에
따라 유용한 선택 도구입니다. `doctor`가 경고로 보고할 수 있지만, Linux 전용
작업의 기준 환경은 Kali WSL입니다.

## 보안 및 재현성

- `input/`은 수정하지 않습니다. 복사본을 `work/`에서 분석합니다.
- 솔버는 플래그 후보를 런타임에 도출해 stdout으로만 출력합니다.
- 라이브 플래그·토큰·자격 증명은 무시되는 `.local/`에만 둡니다.
- tracked notes, evidence, write-up에는 플래그 원문을 쓰지 않습니다.
- `ctf verify`는 후보 누출을 검사하고 증거·입력·솔버의 연결을 검증합니다.
- 외부 플랫폼 제출은 사용자의 명시적 승인 후에만 수행합니다.

원격 저장소는 대회가 진행 중이거나 challenge 자료가 비공개일 때 반드시
private으로 유지하세요.
