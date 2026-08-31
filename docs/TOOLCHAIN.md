# Toolchain status

Last audited: 2026-08-27 on the current Windows host.

## Ready on the host

- Windows PowerShell 5.1
- Git 2.54 and Git LFS 3.7
- Python 3.13 and pip
- Node.js 24 and npm
- `curl.exe` and `tar.exe`

## Present but currently blocked

- WSL 2.9 with a Kali Linux WSL2 distribution is registered.
- This managed session receives `E_ACCESSDENIED` when starting or enumerating WSL. Do not report Kali as missing solely from that error.

## Not yet available on the Windows PATH

- PowerShell 7, Docker/Podman, 7-Zip, jq
- gdb, binutils, file, socat/netcat, QEMU
- Go, Rust, .NET, CMake, GCC, Clang
- uv and pipx

## Recommended next phase

Use Windows only for orchestration and general scripting. Prepare Kali WSL as the primary pwn/reverse/forensics environment, with a dedicated Python virtual environment and the upstream `.agents/skills/scripts/install_ctf_tools.sh` installer. Keep malware execution in an isolated disposable VM rather than disabling host protections.

Run `.\ctf.ps1 doctor` before a competition to distinguish required project failures from optional tool warnings.
