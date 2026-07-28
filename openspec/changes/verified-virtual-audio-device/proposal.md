## Why

UShareIPlay currently requires a physical Android device plus hardware audio loopback, preventing portable operation and repeatable automation. A verified Virtual Audio Device is needed now to remove that dependency without presenting an unverified emulator as a working music-to-microphone solution.

## What Changes

- Add a managed Android Emulator Virtual Audio Device with a visible Play Store AVD for manual application installation and Appium use.
- Add platform-specific Host Audio Loopback setup for macOS BlackHole and Linux PipeWire, while preserving normal host-audio settings after a session.
- Add a deterministic Android playback-to-microphone verifier with retained raw evidence and a required failing negative control.
- Add a disposable rootable AVD fallback that is available only after evidence shows the supported host-loopback route failed.
- Add operator documentation and a single launcher workflow that provisions, opens, and health-checks the Virtual Audio Device.

## Capabilities

### New Capabilities

- `virtual-audio-device`: Provision, start, stop, and connect UShareIPlay to a managed Android Emulator target.
- `audio-loopback-verification`: Produce objective positive and negative-control evidence for Android playback-to-microphone routing.
- `host-audio-loopback`: Configure the supported macOS and Linux host-audio implementations used by a Virtual Audio Device.

### Modified Capabilities

- `local-config`: Permit a generated local override to point Appium at the managed Virtual Audio Device without changing the tracked base configuration.

## Impact

The change adds an operator-facing tooling surface, Android SDK/AVD and host-audio dependencies, a verifier test artifact, generated local configuration, and ignored runtime evidence. Soul and QQ Music automation logic remains unchanged; the existing Appium driver configuration is the integration boundary.
