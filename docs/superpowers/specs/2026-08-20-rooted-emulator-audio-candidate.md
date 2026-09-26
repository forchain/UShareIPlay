# Spec: Automated Rooted macOS Emulator Audio Candidate

## Problem Statement

UShareIPlay currently has a usable Ubuntu Waydroid `Virtual Audio Device`, but that deployment is heavy and its observed VM performance is not ideal for the operator's workflow. A standard Android Emulator on macOS was previously rejected after an unrooted, host-microphone test produced silence; that result does not cover a rooted emulator whose Android audio path is modified inside the disposable guest.

The operator wants a macOS Apple Silicon candidate that isolates Android audio from normal macOS audio services, avoids repeated manual deployment, and can be investigated across several Android-side techniques. The operator should not become the bottleneck for a complex experiment or be expected to remember deployment details after context loss or agent handoff.

## Solution

Build a fully automated `Rooted Emulator Harness` for a disposable Android 30 `google_apis;arm64-v8a` AVD without Play Store. The harness provisions and rebuilds the guest, extracts fixed-version QQ Music and Soul APKs from an explicitly selected `APK Source Device`, applies one candidate audio mechanism at a time, runs independent evidence-producing tests, and pauses only when a human Soul listening check is unavoidable.

Investigate candidates from low to high system coupling:

1. An independently implemented PhantomMic-style file `Microphone Injection` path.
2. A reduced-root or no-root app-process variant if the emulator supports it.
3. An app-process `Live Audio Bridge` from a `Synthetic Playback Source` and then QQ Music into Soul's microphone frames.
4. A rooted Android AudioPolicy, AudioFlinger, virtual-input, or HAL route.
5. A custom emulator host-audio backend only if Android-side candidates fail.

The candidate is promoted only after all required `Acceptance Gate`s pass. Until then, Ubuntu Waydroid remains the supported production backend.

## User Stories

1. As an operator, I want one automated command to provision the rooted AVD, so that I do not configure Android tooling manually.
2. As an operator, I want the rooted AVD to be disposable, so that invasive experiments cannot damage my normal Android Emulator state.
3. As an operator, I want a failed experiment to be safely destroyed and recreated, so that I can retry without manual cleanup.
4. As an operator, I want the harness to resume an interrupted run idempotently, so that a long experiment does not depend on one uninterrupted terminal session.
5. As an operator, I want the harness to report the first failed Acceptance Gate, so that I know which branch stopped and why.
6. As an operator, I want the harness to print and retain an evidence directory, so that another agent can continue from recorded facts.
7. As a maintainer, I want a fixed Android 30 ARM64 Google APIs image, so that root experiments are reproducible on Apple Silicon.
8. As a maintainer, I want no Play Store dependency in the experiment AVD, so that application installation and root modification remain scriptable.
9. As a maintainer, I want emulator and system-image versions recorded for every run, so that native symbol and audio behavior can be compared across environments.
10. As an operator, I want the harness to extract QQ Music and Soul APKs from an explicitly selected authorized Android device, so that I do not have to find or manually copy installation packages.
11. As a maintainer, I want base and split APKs hashed and cached outside Git, so that the exact application inputs are reproducible without exposing proprietary packages in the repository.
12. As an operator, I want the harness to avoid reading application data or credentials from the APK Source Device, so that package extraction cannot become account migration.
13. As an operator, I want a simple AudioRecord Probe that opens the microphone and writes raw frames, so that Android microphone substitution can be tested without Soul's room workflow.
14. As a maintainer, I want the Probe to use `VOICE_COMMUNICATION`, 16 kHz, mono, PCM 16-bit, and blocking `AudioRecord.read()`, so that the first test exercises a realistic voice-capture path.
15. As a maintainer, I want the Probe to retain source PCM, captured PCM, metadata, logs, and hashes, so that injection success is inspectable rather than inferred from a UI label.
16. As a maintainer, I want a deterministic positive injection run, so that captured frames can be matched to a known source fingerprint.
17. As a maintainer, I want a deliberately disabled negative injection run, so that silence or ordinary microphone input cannot be mistaken for successful substitution.
18. As an operator, I want the harness to stop before Soul testing when the Probe fails, so that I do not spend time on a known-bad mechanism.
19. As an operator, I want the same automated injection setup exercised inside Soul after the Probe passes, so that Soul compatibility is tested before any real-time bridge work.
20. As a maintainer, I want Soul process hook or substitution evidence, so that a remote listening result can be tied to the intended Android path.
21. As an operator, I want to perform only the minimum Soul two-account listening check, so that product-specific voice behavior is confirmed without manually deploying the runtime.
22. As a maintainer, I want the Soul positive check to use deterministic test audio, so that the second account's result is distinguishable from ambient sound or accidental playback.
23. As a maintainer, I want the Soul negative check to disable or clear the injection source, so that the positive result has a falsifiable control.
24. As a maintainer, I want emulator host microphone input disabled during Soul checks, so that acoustic host loopback cannot explain a positive result.
25. As an operator, I want the harness to stop the PhantomMic-style branch after an automated compatibility diagnosis if Soul cannot be hooked, so that failed app-process assumptions do not consume the rest of the experiment.
26. As a maintainer, I want a Synthetic Playback Source that emits deterministic PCM through normal Android playback, so that bridge mechanics can be tested without QQ Music login, catalog availability, or application-specific behavior.
27. As a maintainer, I want the synthetic source to use the same automated evidence protocol as QQ Music, so that the two source paths can be compared directly.
28. As an operator, I want a Live Audio Bridge to replace Soul's microphone completely, so that the first implementation does not depend on host microphone permissions or audio mixing.
29. As a maintainer, I want only QQ Music audio selected for the bridge, so that Soul participants, notifications, and unrelated applications cannot create feedback loops.
30. As a maintainer, I want the bridge to avoid an intermediate recording file in steady state, so that the result represents live playback rather than delayed file replay.
31. As an operator, I want the bridge to recover after synthetic-player or QQ Music pause and resume, so that normal playback controls do not permanently break the microphone path.
32. As a maintainer, I want a 30-minute bridge run without crashes, permanent interruptions, unbounded buffering, or accumulating drift, so that continuity is prioritized over low latency.
33. As an operator, I want no strict latency requirement, so that the experiment can choose robust buffering and conversion over fragile low-latency tuning.
34. As an operator, I want QQ Music guest or free playback to be sufficient, so that QQ Music login and account risk checks do not block bridge validation.
35. As a maintainer, I want QQ Music source compatibility tested only after the synthetic bridge passes, so that failures can be attributed to QQ Music rather than the bridge itself.
36. As a maintainer, I want rooted system-level routes available as a later branch, so that AudioPolicy, AudioFlinger, virtual input, and HAL approaches can be evaluated when app-process hooks are insufficient.
37. As an operator, I want Android guest security controls to be relaxable when required, so that root experiments are not blocked by controls that do not protect my macOS host.
38. As a maintainer, I want guest-only security relaxation bounded to the disposable AVD, so that macOS security, default audio devices, and unrelated host services remain untouched.
39. As a maintainer, I want the harness to preserve a post-install baseline snapshot, so that candidates can reuse application state without sharing modified system state.
40. As a maintainer, I want candidate-specific state and evidence isolated, so that one failed system modification cannot contaminate another candidate's result.
41. As an operator, I want the harness to keep a successful candidate available for later manual Soul and Appium checks, so that I do not repeat setup after every gate.
42. As a maintainer, I want existing Appium and local configuration boundaries reused, so that Soul and QQ Music automation logic does not need a parallel device implementation.
43. As an operator, I want the candidate to leave macOS default input and output unchanged before, during, and after operation, so that my normal audio services remain usable.
44. As a maintainer, I want existing objective audio analysis reused or extended at its highest seam, so that positive and negative signal criteria remain consistent with the Waydroid backend.
45. As a maintainer, I want every candidate report to distinguish `passed`, `failed`, and `blocked-on-human-auth`, so that an authorization prompt is not misreported as an audio failure.
46. As a maintainer, I want the promotion decision to require all gates on a clean reproducible run, so that a plausible demo cannot replace a verified backend.
47. As an operator, I want Waydroid to remain available while this candidate is investigated, so that the experiment does not interrupt the existing usable workflow.

## Implementation Decisions

- The top-level integration seam is the `Rooted Emulator Harness`. It owns provisioning, lifecycle, guest modification, APK handling, candidate selection, test execution, evidence, retry, and cleanup.
- The experiment target is a named disposable Android 30 `google_apis;arm64-v8a` AVD without Play Store. The standard Play Store AVD remains a UI-only control.
- The harness uses an explicitly selected `APK Source Device` and extracts package installation artifacts without copying application data or credentials. APKs remain outside Git and are identified by hashes.
- All operations are automated from the first attempt. Human intervention is limited to unavoidable host or guest authorization prompts, Soul login or anti-abuse checks, and the final Soul two-account listening check. QQ Music login is not required.
- A fixed baseline snapshot separates application state from candidate-specific rooted system changes. Candidate retries reuse their own state; new system branches start from the clean baseline.
- The first injection implementation is behaviorally informed by PhantomMic but independently implemented because the referenced upstream repository has no license suitable for source incorporation.
- The audio contract is complete microphone replacement, not mixing with a real microphone. The bridge targets QQ Music only and excludes Soul, notification, and unrelated playback.
- The bridge is first validated with a `Synthetic Playback Source`, then with QQ Music guest or free playback. QQ Music compatibility is not used to diagnose the bridge before the synthetic stage passes.
- Candidate order is app-process file injection, reduced-root or no-root variant, app-process live bridge, rooted Android system route, and finally custom host-audio backend.
- Guest-only security relaxation, including root, remount, system-library changes, policy changes, or SELinux changes, is permitted when required. Host security and host audio defaults are not modified.
- The Probe and synthetic player are small Android test clients with deterministic artifacts. The existing host-side analyzer remains the highest-level signal-analysis seam.
- Appium integration continues through the current local configuration override and driver boundary. Soul and QQ Music application automation remains unchanged.
- Candidate promotion requires Gates 0 through 5 in the durable acceptance contract: Harness Repeatability, Probe Injection, Soul Hook Gate, Synthetic Live Audio Bridge and QQ Music Source Compatibility, Existing Objective Audio Verification, and UShareIPlay Integration.
- Candidate evidence is immutable per run and includes environment manifest, command and service logs, source and capture PCM, hashes, reports, candidate configuration, AVD properties, and final gate status.

## Testing Decisions

- Tests validate external behavior at the highest available seam. Unit tests should verify the harness planner, command construction, AVD safety boundaries, APK manifest and hash handling, snapshot state transitions, evidence naming, and report classification without requiring Android.
- The AudioRecord Probe integration test is the first black-box audio seam. It must run both enabled and disabled injection modes and retain raw artifacts; hook logs alone are insufficient.
- The Probe positive result must match a deterministic source fingerprint, while the disabled negative result must fail amplitude or fingerprint criteria. A negative control that passes invalidates the run.
- Soul compatibility is a manual black-box acceptance check triggered only after automated Probe success. It requires deterministic positive listening, disabled negative listening, hook or substitution logs, and disabled emulator host microphone input.
- The Synthetic Playback Source bridge test must prove a no-file steady-state path, pause/resume recovery, 30-minute continuity, bounded buffering, and no unbounded drift before QQ Music is attempted.
- QQ Music source compatibility must use the same bridge evidence protocol, with separate reports from the synthetic source. Guest or free playback is sufficient.
- Existing `audio_loopback_analysis` and `loopback_verification` prior art remains the basis for raw PCM, SHA-256, multi-tone, amplitude, and negative-control analysis. Any extension must preserve existing Waydroid acceptance behavior.
- The final integration test must target the active emulator through Appium and confirm that macOS default audio devices are unchanged. A successful application launch without audio evidence is not acceptance.
- A clean rebuild or baseline-clone run is required before promotion, so that a stateful one-off experiment cannot be treated as reproducible.

## Out of Scope

- Replacing or deprecating the supported Ubuntu Waydroid backend before the macOS candidate passes every required gate.
- Play Store support or Google-account provisioning in the rooted experiment AVD.
- Mixing real microphone input with QQ Music in the first implementation.
- A strict low-latency or audio-video synchronization guarantee.
- Automatic Soul room, account, CAPTCHA, or anti-abuse workflows that require human identity decisions.
- Copying PhantomMic source code into the repository or treating its unlicensed repository as a distributable dependency.
- Committing QQ Music or Soul APKs, application data, credentials, or login state to Git.
- Windows or other host-platform support.
- Claiming that a generic Probe pass proves Soul's production voice SDK compatibility.
- Modifying macOS default input/output devices, host security, kernel controls, or unrelated host audio services.

## Further Notes

The existing verified Waydroid documentation and ADR remain the production reference and fallback. The durable acceptance contract for this candidate is recorded separately in the repository's virtual emulator experiment documentation, and this issue is the implementation handoff for that contract. The current APK Source Device observation provides QQ Music `20.4.0.5` and Soul `6.31.0` as the initial fixed seed; the harness must record the actual hashes at runtime.
