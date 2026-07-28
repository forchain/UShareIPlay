## Context

The existing configuration targets a physical Android device through Appium. Android Emulator officially supports routing host microphone input into an AVD, while macOS and Linux can expose a playback loopback as that input. The referenced research repository contains no executable implementation and proposes image-level modifications that are unnecessary until the supported route has objectively failed.

## Goals / Non-Goals

**Goals:**
- Replace the physical target with a managed visible AVD that retains manually installed applications.
- Keep UShareIPlay application automation unchanged by integrating through its existing local configuration and Appium boundary.
- Make generic playback-to-microphone success falsifiable through a negative control and inspectable artifacts.
- Isolate experimental root changes to a disposable fallback AVD.

**Non-Goals:**
- Prove Soul's production voice SDK compatibility automatically.
- Modify Android Audio HAL, the long-lived AVD system image, or host security settings in the standard route.
- Support Windows or Linux hosts without PipeWire.

## Decisions

### A managed tool owns named AVDs and generated local state

A Python command-line tool owns only `ushareiplay-audio`, `ushareiplay-audio-root`, its generated local Appium override, verifier artifacts, and children. It discovers SDK tools from conventional locations or environment variables. This is chosen over editing the tracked configuration because local overrides are already the project seam for per-machine device data.

### Two distinct AVD contracts

The default AVD uses the current ARM64 Google Play image and remains unrooted so the operator can install applications normally. The fallback uses a separate ARM64 Google APIs image because Play Store images cannot elevate through adb. This is chosen over converting the default instance because it preserves installed application state and makes fallback cleanup a deletion rather than a repair.

### Host audio loopback is the default router

On macOS the selected driver is BlackHole 2ch; on Linux the selected service is PipeWire. The tool enables the Emulator host microphone input explicitly on each start, since Emulator disables it by default. This is chosen over HAL, LSPosed, Magisk, or ALSA-module work because it relies on supported host and Emulator interfaces and is reversible.

### The verifier is an independent Android client plus host analyzer

An Android test application emits a deterministic multi-tone/chirp sequence to a normal playback stream and records the normal microphone stream. The host analyzer pulls immutable raw data, computes lag-aware normalized correlation, spectral frequency error, SNR, and amplitude, then writes a JSON report and hashes. A disabled-loopback run is required to fail before the enabled-loopback run is eligible to pass. This avoids a test that can pass because it copied generated samples directly into the recording result.

### Root fallback is evidence-gated

Only a retained failed standard verification result enables root fallback. The fallback may rebuild and alter the dedicated virtual disk but MUST not alter host security controls. This is chosen over automatic escalation because Android image modifications are less stable and make support failures harder to diagnose.

## Risks / Trade-offs

- BlackHole installation requires a host restart -> setup reports restart-required and refuses readiness until the device is visible.
- macOS CoreAudio device selection can interrupt desktop audio -> save the prior default devices and restore them on stop and error paths.
- Emulator or target apps may reject emulation -> report this separately from Audio Loopback Verification; do not substitute app behavior for routing evidence.
- Standard Emulator audio may not expose playback to the selected host device -> retain the failed evidence and enter the explicit fallback path rather than claiming success.
- A test application requires Android build tooling -> bootstrap the exact SDK/JDK dependencies, and fail with actionable diagnostics when a host cannot supply them.

## Migration Plan

1. Add tool and unit tests without changing existing device defaults.
2. Provision and verify the default AVD, then generate an ignored local override only when the operator selects it.
3. Use the new launcher for manual application installation and UShareIPlay runs.
4. Stop restores saved host-audio defaults; deleting either named AVD rolls back its Android state.
