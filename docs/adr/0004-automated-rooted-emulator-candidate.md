# Automate a disposable rooted macOS Emulator candidate

The project will investigate a rooted Android 30 `arm64-v8a` AVD on macOS as an automated, evidence-gated candidate for replacing the Waydroid `Virtual Audio Device`. The `Rooted Emulator Harness` owns provisioning, system modification, APK extraction, testing, evidence, and rebuilds; human intervention is limited to unavoidable authorization, account verification, and final Soul listening. The candidate must pass independent probe injection, Soul compatibility, QQ Music-only live bridging, objective audio verification, and UShareIPlay integration before it can replace the supported Waydroid backend.

## Considered Options

- Manual rooted AVD setup: rejected because it makes the operator a bottleneck and cannot be reproduced after context loss or handoff.
- Standard unrooted Play Store AVD: retained only for UI control; its host microphone path already failed controlled verification.
- Ubuntu Waydroid: remains the supported backend and fallback while the macOS candidate is investigated.

## Consequences

The experiment can modify or weaken security controls inside the disposable Android guest, but it must not alter macOS audio defaults or host security. APKs and credentials remain outside Git. All implementation branches share the acceptance contract in `docs/virtual-audio-emulator-experiment.md`.
