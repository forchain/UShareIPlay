## Why

UShareIPlay currently requires a physical Android device plus hardware audio loopback, preventing portable operation and repeatable automation. A verified Virtual Audio Device is needed now to remove that dependency without presenting an unverified emulator as a working music-to-microphone solution.

## What Changes

- Add a managed Android Emulator Virtual Audio Device with a visible Play Store AVD for manual application installation and Appium use.
- Retain the macOS AVD only for manual application installation and Appium UI use; investigate a Linux PipeWire Android backend for audio routing.
- Add a deterministic Android playback-to-microphone verifier with retained raw evidence and a required failing negative control.
- Gate every proposed audio backend, including any root fallback, behind retained positive and negative-control evidence.
- Add operator documentation and a single launcher workflow that provisions, opens, and health-checks the Virtual Audio Device.

## Capabilities

### New Capabilities

- `virtual-audio-device`: Provision, start, stop, and connect UShareIPlay to a managed Android Emulator target.
- `audio-loopback-verification`: Produce objective positive and negative-control evidence for Android playback-to-microphone routing.
- `host-audio-loopback`: Verify a Linux PipeWire Android backend without changing a macOS operator's default microphone.

### Modified Capabilities

- `local-config`: Permit a generated local override to point Appium at the managed Virtual Audio Device without changing the tracked base configuration.

## Impact

The change adds an operator-facing AVD launcher, a verifier test artifact, generated local configuration, and retained runtime evidence. Soul and QQ Music automation logic remains unchanged; the existing Appium driver configuration is the integration boundary.
