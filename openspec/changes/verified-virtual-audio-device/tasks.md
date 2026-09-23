## 1. Managed Virtual Audio Device lifecycle

- [x] 1.1 Implement and unit-test AVD specification, host-platform detection, SDK discovery, and safe command construction.
- [ ] 1.2 Implement default AVD provisioning, visible launch, serial discovery, and generated local Appium override while preserving unrelated local configuration.
- [ ] 1.3 Implement guarded root-fallback provisioning that requires retained standard-route failure evidence.

## 2. Host Audio Loopback

- [x] 2.1 Evaluate the standard macOS Emulator host-input route with reversible state capture and restoration; reject it for microphone routing when Android capture remains silent.
- [x] 2.2 Implement and verify a Linux Waydroid/PipeWire session with an owned sink/monitor and exact default-device restoration.
- [x] 2.3 Confirm that Emulator host microphone input is opt-in only, uses the host default input, and is not enabled by the normal launcher.

## 3. Audio Loopback Verification

- [ ] 3.1 Add a deterministic Android playback-and-microphone verifier and reproducible build/install workflow.
- [ ] 3.2 Implement the host analyzer, immutable evidence artifacts, fixed thresholds, and negative-control gate.
- [ ] 3.3 Add unit tests for analyzer behavior, evidence validity, and failure diagnostics.

## 4. Operator Workflow and Real Verification

- [x] 4.1 Add documented setup, launch, stop, and verification workflows for the supported Linux backend; preserve the macOS Emulator launch workflow as UI-only.
- [x] 4.2 Provision the default AVD and execute the required standard-Emulator negative and host-loopback attempts; retain evidence and reject the route when the positive capture fails.
- [x] 4.3 Avoid root fallback because the Linux standard backend passed the retained positive and negative-control acceptance test.

## 5. Completion

- [x] 5.1 Run focused and full Python test suites plus syntax checks.
- [x] 5.2 Audit every requirement against retained runtime evidence and update the operator documentation with the final supported result.
