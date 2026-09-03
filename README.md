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

`shared/ctf-ecc-on-demand.md`에는 소스 취약점 triage, Python 솔버 품질,
구조화 파싱, EVM Keccak 주의사항 등 선별된 ECC 지침이 있습니다. 필요할
때만 읽어 스킬 context를 작게 유지합니다.

## 환경

- Windows 호스트 스크립트는 PowerShell 5.1 호환성을 유지합니다.
- Linux 우선 pwn/reverse/forensics/malware 작업은 Kali WSL을 사용합니다.
- Kali CTF 환경에서 실행하려면:

  ```powershell
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-CtfWsl.ps1 `
    verify c\example-2026\pwn\example --record
  ```

- 필요한 도구는 `scripts\Install-CtfWsl.ps1`로 설치하고,
  `doctor --wsl-tools`로 다시 검증할 수 있습니다.

## 보안 및 재현성

- `input/`은 수정하지 않습니다. 복사본을 `work/`에서 분석합니다.
- 솔버는 플래그 후보를 런타임에 도출해 stdout으로만 출력합니다.
- 라이브 플래그·토큰·자격 증명은 무시되는 `.local/`에만 둡니다.
- tracked notes, evidence, write-up에는 플래그 원문을 쓰지 않습니다.
- `ctf verify`는 후보 누출을 검사하고 증거·입력·솔버의 연결을 검증합니다.
- 외부 플랫폼 제출은 사용자의 명시적 승인 후에만 수행합니다.

원격 저장소는 대회가 진행 중이거나 challenge 자료가 비공개일 때 반드시
private으로 유지하세요.
