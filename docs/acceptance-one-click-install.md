# Acceptance Specification: Ubuntu One-Click Installer and Cloud VM Automation Host

This document defines the strict, objective, and reproducible acceptance criteria for the UShareIPlay Ubuntu One-Click Installer (`install.sh`). Any independent testing agent or human operator can evaluate and verify the deployment against this specification.

---

## 1. System Environment & Prerequisites

- **Operating System**: Ubuntu Linux 24.04 LTS (recommended: ARM64 / `aarch64` VM in Parallels or bare metal).
- **Target Host**: e.g., `devops@192.168.8.105`.
- **Privileges**: User with passwordless `sudo` privileges.
- **Hardware Resources**: Minimum 4 vCPUs, 8 GB RAM, 20 GB free disk space.

---

## 2. Automated Provisioning Scope

Running `install.sh` executes end-to-end idempotent provisioning:

1. **System Tools & Runtimes**:
   - OS packages: `git`, `curl`, `iptables`, `iptables-persistent`, `netfilter-persistent`, `pipewire-pulse`, `wireplumber`, `pulseaudio-utils`, `adb`, `wget`, `jq`.
   - Node.js LTS, Appium 2.x server, and `uiautomator2` driver.
   - Astral `uv` Python package manager and Python 3.12+ environment.
2. **Repository & Dependencies**:
   - Clones / updates repository to target directory (default: `~/UShareIPlay`).
   - Generates `.venv` and synchronizes Python dependencies via `uv sync`.
   - Initializes `config.local.yaml` from `config.local.yaml.example` if not present.
3. **Virtual Audio Device (Waydroid)**:
   - Configures binder kernel modules (`binder_linux`).
   - Installs and initializes Waydroid LineageOS image.
   - Starts `waydroid-container` service and user session.
4. **Application Packages (APKs)**:
   - Installs QQ Music (`com.tencent.qqmusic`).
   - Installs Soul App (`cn.soulapp.android`).
   - Installs Loopback Verifier (`io.ushareiplay.loopback`).
   - Grants Android microphone and audio permissions.
5. **Host Audio Loopback (PipeWire)**:
   - Configures owned `ushareiplay_music_sink` null-sink.
   - Routes Android playback to the sink monitor as default input source.
6. **Persistent ADB Port Forwarding**:
   - Enables Linux kernel packet forwarding (`net.ipv4.ip_forward=1`).
   - Sets up iptables DNAT (host port 5555 -> Waydroid container IP:5555) and FORWARD rules.
   - Installs and enables `ushareiplay-adb-forward.service` to dynamically maintain rules across reboots and container renewals.
7. **Appium Background Service**:
   - Configures and enables `ushareiplay-appium.service` (listening on `0.0.0.0:4723`).
8. **Runtime Entry Point**:
   - Updates `run.sh` with automated pre-flight checks (ADB, Appium, Audio sink).

---

## 3. Objective Acceptance Checklist

Each verification step must produce deterministic proof.

| # | Acceptance Criterion | Verification Command | Expected Outcome |
|---|----------------------|----------------------|------------------|
| **AC-1** | **Idempotent Installation** | `bash install.sh` | Exits with return code `0`. Re-running does not fail or duplicate rules. |
| **AC-2** | **Waydroid Status** | `waydroid status` | `Session: RUNNING`, `Container: RUNNING`, `IP address: 192.168.240.x`. |
| **AC-3** | **Application Installation** | `adb shell pm list packages \| grep -E 'soulapp\|qqmusic\|loopback'` | Outputs `package:cn.soulapp.android`, `package:com.tencent.qqmusic`, and `package:io.ushareiplay.loopback`. |
| **AC-4** | **Audio Loopback Route** | `pactl info \| grep -E 'Default Sink\|Default Source'` | Default Sink contains `ushareiplay_music_sink` and Default Source contains `ushareiplay_music_sink.monitor`. |
| **AC-5** | **Kernel Packet Forwarding** | `sysctl net.ipv4.ip_forward` | Outputs `net.ipv4.ip_forward = 1`. |
| **AC-6** | **iptables Port 5555 Forwarding** | `sudo iptables -t nat -L PREROUTING -n -v \| grep 5555` | Shows DNAT rule targeting `<container-ip>:5555`. |
| **AC-7** | **External ADB Connectivity** | `adb connect <vm-ip>:5555 && adb -s <vm-ip>:5555 shell getprop ro.build.version.release` | Successfully connects and returns Android release (e.g. `13` or `11`). |
| **AC-8** | **Appium Service Status** | `curl -s http://127.0.0.1:4723/status \| jq .value.ready` | Returns `true`. |
| **AC-9** | **Python Environment & Dependencies** | `cd ~/UShareIPlay && uv run python -c "import appium, yaml; print('OK')"` | Outputs `OK`. |
| **AC-10** | **run.sh Pre-flight Validation** | `./run.sh --check-only` (or pre-flight check) | Passes all dependency, ADB, Appium, and audio routing assertions. |

---

## 4. Verification Execution Guide for Independent Test Agents

An independent test agent must execute the following sequence:

```bash
# 1. SSH into the test host
ssh devops@192.168.8.105

# 2. Run / update installer
cd ~/UShareIPlay || (git clone https://github.com/forchain/UShareIPlay.git ~/UShareIPlay && cd ~/UShareIPlay)
bash install.sh

# 3. Execute acceptance suite and collect evidence
systemctl is-active waydroid-container
waydroid status
adb shell pm list packages | grep -E 'soulapp|qqmusic|loopback'
pactl info | grep -E 'Default Sink|Default Source'
sudo iptables -t nat -L PREROUTING -n -v | grep 5555
curl -s http://127.0.0.1:4723/status | jq .value.ready
cd ~/UShareIPlay && uv run pytest -q tests/test_db_manager.py
```

Record the stdout/stderr for each step and generate the test evidence report.
