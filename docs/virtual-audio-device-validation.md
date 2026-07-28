---
covers: [Virtual Audio Device, Audio Loopback Verification]
last-synced: 2026-07-28
---

## Standard Emulator Result

The standard Android Emulator route is rejected for music-to-microphone use on this host. The AVD was created from `system-images;android-36;google_apis_playstore;arm64-v8a` and a verifier APK used standard Android `AudioTrack` playback plus `AudioRecord` microphone capture at 8 kHz.

| Run | Host input | Emulator host mic | Capture result |
| --- | --- | --- | --- |
| Negative control | EarPods Microphone | disabled | Expected failure: amplitude `0.00012`, correlation `0.00309` |
| Host-loopback attempt | Loopback `IINA` | enabled | Failure: all-zero capture; Ranchu HAL reported repeated input I/O errors and inserted silence |

The input device was restored to `EarPods Microphone` and Emulator host mic was disabled after the attempt. The host-loopback attempt does not prove Loopback emitted audio, so it is not evidence against Loopback itself. It does prove that no successful Android microphone capture was observed, and standard Emulator requires the host default input even if it later works.

## Acceptance Rule

No backend is ready until it produces both of the following artifacts:

1. A disabled-route negative control that fails correlation, frequency, or amplitude checks.
2. An enabled-route positive control that meets the fixed correlation, frequency, SNR, and amplitude thresholds.

Raw source and capture PCM, hashes, command logs, and the machine-readable report must be retained for both runs.

## Next Backend

The next candidate is an Ubuntu host using Waydroid with PipeWire. It must expose a dedicated PipeWire virtual source to Android without changing macOS device defaults, then pass the same acceptance rule. This is a new backend investigation, not a claimed solution.
