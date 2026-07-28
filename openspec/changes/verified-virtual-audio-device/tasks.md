## 1. Managed Virtual Audio Device lifecycle

- [x] 1.1 Implement and unit-test AVD specification, host-platform detection, SDK discovery, and safe command construction.
- [ ] 1.2 Implement default AVD provisioning, visible launch, serial discovery, and generated local Appium override while preserving unrelated local configuration.
- [ ] 1.3 Implement guarded root-fallback provisioning that requires retained standard-route failure evidence.

## 2. Host Audio Loopback

- [ ] 2.1 Implement macOS BlackHole readiness detection, audio-session state capture, and restoration behavior.
- [ ] 2.2 Implement Linux PipeWire readiness detection and reversible loopback session behavior.
- [ ] 2.3 Enable Emulator host microphone input for managed sessions and record host-audio setup diagnostics.

## 3. Audio Loopback Verification

- [ ] 3.1 Add a deterministic Android playback-and-microphone verifier and reproducible build/install workflow.
- [ ] 3.2 Implement the host analyzer, immutable evidence artifacts, fixed thresholds, and negative-control gate.
- [ ] 3.3 Add unit tests for analyzer behavior, evidence validity, and failure diagnostics.

## 4. Operator Workflow and Real Verification

- [ ] 4.1 Add documented setup, launch, stop, verify, and Appium workflows for macOS and Linux.
- [ ] 4.2 Install/configure the macOS backend, provision the default AVD, and execute the required negative and positive real-device verification runs.
- [ ] 4.3 If and only if standard verification fails, execute and document the root-fallback investigation with retained evidence.

## 5. Completion

- [ ] 5.1 Run focused and full Python test suites plus syntax checks.
- [ ] 5.2 Audit every requirement against retained runtime evidence and update the operator documentation with the final supported result.
