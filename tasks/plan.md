# Implementation Plan: Automated Rooted macOS Emulator Audio Candidate

## Overview

Implement GitHub issue #254 through one top-level `Rooted Emulator Harness`. The harness reuses the existing AVD launcher, audio analyzer, verifier artifacts, and Appium override seam. Work proceeds through the documented Acceptance Gates, with an automated test and retained evidence at every boundary.

## Architecture Decisions

- Keep `scripts/virtual_audio_device.py` as the low-level Android SDK/AVD adapter and add one harness above it.
- Extend the existing loopback verifier APK with explicit Probe and Synthetic Playback modes instead of introducing unrelated Android projects.
- Keep pure planning, manifest, APK extraction, hashing, and gate classification logic testable without Android.
- Treat app-process injection, live bridging, and system/HAL routing as candidate plugins selected by the harness, not hard-coded lifecycle branches.
- Store run evidence outside Git and never mutate the supported Waydroid backend.

## Dependency Graph

Harness run/evidence model
    |
    +-- APK Source Device extraction
    |
    +-- rooted AVD lifecycle and baseline
    |
    +-- Probe and Synthetic Playback APK modes
            |
            +-- file Microphone Injection candidate
                    |
                    +-- Soul Hook Gate
                            |
                            +-- Synthetic Live Audio Bridge
                                    |
                                    +-- QQ Music compatibility
                                            |
                                            +-- objective verifier and Appium promotion

## Task List

### Phase 1: Automated Foundation

- [x] Task 1: Add the run manifest, gate status model, immutable evidence layout, and harness CLI skeleton.
- [x] Task 2: Add APK Source Device discovery, base/split extraction, SHA-256 caching, and manifest output.
- [x] Task 3: Add rooted AVD prepare/open/health/rebuild commands and candidate-safe state ownership.

### Checkpoint: Foundation

- [ ] Focused harness and existing Virtual Audio Device tests pass.
- [ ] A dry run reports commands and evidence paths without mutating unrelated AVDs or host audio.

### Phase 2: Independent Android Gates

- [x] Task 4: Extend the verifier APK with AudioRecord Probe mode and deterministic capture artifacts.
- [x] Task 5: Extend the verifier APK with a controllable Synthetic Playback Source mode.
- [x] Task 6: Automate APK build, install, permission grant, mode execution, artifact pull, and analysis.

### Checkpoint: Probe and Playback

- [x] Android client builds and installs on the rooted AVD.
- [x] Probe negative control and synthetic playback artifacts are retained and classified.

### Phase 3: Injection and Target Compatibility

- [x] Task 7: Implement the first automated app-process file Microphone Injection candidate.
- [x] Task 8: Run Gate 1 positive/negative evidence and automate compatibility diagnostics.
- [x] Task 9: Prepare the automated Soul Hook Gate and pause only for the two-account listening result.

### Checkpoint: Microphone Injection

- [x] Probe injection passes with a failing negative control.
- [x] Harness reports either `passed`, `failed`, or `blocked-on-human-auth` for Soul.

### Phase 4: Live Audio Bridge

- [ ] Task 10: Bridge Synthetic Playback Source PCM into target microphone frames without a steady-state file (AudioPlaybackCapture primitive is implemented; Soul bridge awaits Gate 2).
- [ ] Task 11: Add pause/resume, bounded buffering, drift telemetry, and 30-minute stability execution.
- [ ] Task 12: Replace the synthetic source with QQ Music guest/free playback and retain separate evidence.

### Checkpoint: Live Bridge

- [ ] Synthetic and QQ Music source reports are separate and reproducible.
- [ ] Only the selected source is bridged; unrelated Android playback is excluded.

### Phase 5: Fallback and Promotion

- [ ] Task 13: Attempt AudioPolicy/AudioFlinger/virtual-input/HAL candidate only if the app-process branch fails.
- [ ] Task 14: Run existing objective audio verification and negative controls against the winning candidate.
- [ ] Task 15: Validate Appium integration and unchanged macOS input/output defaults on a clean run.

### Checkpoint: Complete

- [ ] Gates 0 through 5 are represented in the final report.
- [ ] Waydroid remains supported unless every promotion gate passes.
- [ ] Full pytest suite and Android syntax/build checks pass.

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Soul uses a non-hooked native voice path | High | Gate Soul before live-bridge work; pivot to system route after one automated diagnosis. |
| Android Emulator native symbols vary | High | Pin emulator/system image, record hashes, resolve symbols at runtime, and keep candidate-specific diagnostics. |
| APKs contain splits or ABI constraints | High | Extract every `pm path`, install as a set, and verify package ABI/version before gates. |
| Guest modifications corrupt the AVD | Medium | Use named disposable state and rebuild from a clean baseline. |
| Audio buffering grows without bound | High | Use bounded queues, drop/realign policy, and explicit drift telemetry. |
| Host audio is accidentally changed | High | Snapshot macOS defaults before/after and fail promotion on any difference. |

## Open Questions

- None requiring pre-implementation user input. Human action is deferred until the first candidate reaches the Soul listening gate.
