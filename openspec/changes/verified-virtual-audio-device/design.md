## Context

The existing configuration targets a physical Android device through Appium. The referenced research repository contains no executable implementation. A standard Android Emulator attempt on macOS has now objectively failed its Android `AudioRecord` test and requires the host default input, so that route is excluded from music-to-microphone delivery.

## Goals / Non-Goals

**Goals:**
- Provide a managed visible AVD that retains manually installed applications for Appium UI work.
- Investigate a Linux Android backend with PipeWire-owned routing that can replace the physical target only after it passes the verifier.
- Keep UShareIPlay application automation unchanged by integrating through its existing local configuration and Appium boundary.
- Make generic playback-to-microphone success falsifiable through a negative control and inspectable artifacts.
- Isolate experimental root changes to a disposable fallback AVD.

**Non-Goals:**
- Prove Soul's production voice SDK compatibility automatically.
- Modify Android Audio HAL, the long-lived AVD system image, or host security settings in the standard route.
- Support Windows, or claim Linux audio routing before a real Linux backend passes the verifier.

## Decisions

### A managed tool owns named AVDs and generated local state

A Python command-line tool owns only `ushareiplay-audio`, `ushareiplay-audio-root`, its generated local Appium override, verifier artifacts, and children. It discovers SDK tools from conventional locations or environment variables. This is chosen over editing the tracked configuration because local overrides are already the project seam for per-machine device data.

### macOS AVD is a UI-only contract

The default AVD uses the current ARM64 Google Play image and remains unrooted so the operator can install applications normally. It is intentionally started without host-audio input. Any root-capable Android image is an isolated Linux investigation, not a fallback that turns the Emulator route into a working audio backend.

### Linux Waydroid PipeWire backend is the default router

The macOS Emulator launcher keeps host-audio disabled by default because enabling it injects the host default input and still produced silence in Android. Ubuntu Waydroid uses PipeWire PulseAudio compatibility with a dedicated sink and its monitor source. The verifier passed a direct Android playback-to-microphone run with the route enabled and failed with the route disabled. The backend does not rely on macOS defaults.

### The verifier is an independent Android client plus host analyzer

An Android test application emits a deterministic multi-tone/chirp sequence to a normal playback stream and records the normal microphone stream. The host analyzer pulls immutable raw data, computes lag-aware normalized correlation, spectral frequency error, SNR, and amplitude, then writes a JSON report and hashes. A disabled-loopback run is required to fail before the enabled-loopback run is eligible to pass. This avoids a test that can pass because it copied generated samples directly into the recording result.

### Root fallback is evidence-gated and Linux-only

Only a retained failed standard verification result enables root investigation. It may alter a dedicated Linux Android runtime but MUST not alter host security controls or the macOS desktop. This is chosen over automatic escalation because Android image modifications are less stable and make support failures harder to diagnose.

## Risks / Trade-offs

- The standard macOS Emulator AudioRecord path produced silence; it is not a supported audio backend.
- Linux Android runtimes may have incompatible audio integration; report this separately from Audio Loopback Verification and do not substitute device status for captured-signal evidence.
- A test application requires Android build tooling -> bootstrap the exact SDK/JDK dependencies, and fail with actionable diagnostics when a host cannot supply them.

## Migration Plan

1. Add tool and unit tests without changing existing device defaults.
2. Provision the default AVD and generate an ignored local override only when the operator selects it for UI work.
3. Use the verified Linux backend for UShareIPlay runs, retaining a new evidence directory whenever the audio implementation changes.
4. Stop deletes or restores only resources owned by the verified Linux backend.
