# macOS Rooted Emulator Audio Experiment

This document is the durable acceptance contract for investigating a macOS Apple Silicon Android Emulator as a candidate `Virtual Audio Device`. It is intentionally separate from the supported Ubuntu Waydroid backend. A candidate can replace Waydroid only after every required gate below passes.

## Objective

Make QQ Music audio available to Soul as a complete microphone replacement inside a disposable rooted Android 30 AVD, while leaving macOS audio defaults and unrelated host audio services unchanged.

The experiment prioritizes continuity over low latency. It does not require audio and video synchronization. It must be fully automated by the `Rooted Emulator Harness` except for unavoidable authorization prompts, app login or anti-abuse verification, and the final two-account Soul listening check.

## Fixed Starting Environment

- Host: macOS on Apple Silicon (`arm64`).
- AVD: `ushareiplay-audio-root`, Android 30 `google_apis;arm64-v8a`, no Play Store.
- Emulator: version and build recorded in every evidence manifest; the current seed is Emulator 36.1.9.0.
- Applications: APKs extracted from an explicitly selected `APK Source Device`, then cached outside Git with SHA-256 hashes.
- Current observed seed application versions: QQ Music `20.4.0.5`, Soul `6.31.0`.
- The standard Play Store AVD remains a UI-only control and is not an audio candidate.

### Camera Mapping (macOS)

The Android Emulator can consume macOS AVFoundation cameras directly. On the
current Mac, the wired phone is registered by macOS as `iPhone 15 Pro Max
Camera`, and the Emulator enumerates it as `webcam0`:

```text
emulator -webcam-list
Camera 'webcam0' ... DFCC739E-E75E-4C96-8AD5-C7CD00000001
```

The rooted harness starts the AVD with:

```text
-camera-front webcam0 -camera-back emulated
```

This is required because the Soul startup flow requests a front camera. The
previous AVD configuration had `hw.camera.front=none`, which caused
`CameraService` to reject Soul with `No camera device with ID "" is available`.
The mapping does not alter macOS default audio devices. If the phone is
disconnected, enumerate cameras again and either reconnect it or override the
front camera mode with `--camera-front emulated` when launching the generic
device script.

### New-Mac Reproduction Checklist

On a second Mac, run these checks from a clean checkout. They are intentionally
read-only until the AVD is opened:

```bash
source .venv/bin/activate
ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT

"$ANDROID_SDK_ROOT/emulator/emulator" -version
"$ANDROID_SDK_ROOT/emulator/emulator" -webcam-list
adb devices -l
```

The phone must first appear in macOS `system_profiler SPCameraDataType` and
then in `emulator -webcam-list`. Use the reported Emulator name, normally
`webcam0`, when opening the AVD:

```bash
uv run python scripts/rooted_emulator_harness.py prepare-root
uv run python scripts/rooted_emulator_harness.py open-root \
  --port 5558 \
  --camera-front webcam0 \
  --camera-back emulated \
  --config-path config.local.yaml
uv run python scripts/rooted_emulator_harness.py health-root --serial emulator-5558
```

If the new Mac enumerates the phone as `webcam1` or another name, replace
`webcam0`; do not edit the AVD image. Install the cached APKs from the source
device, or extract them on the new host and retain their hashes:

```bash
uv run python scripts/rooted_emulator_harness.py extract-apks \
  --source-serial <authorized-source-device>
uv run python scripts/rooted_emulator_harness.py install-apks \
  --serial emulator-5558 \
  ~/ushareiplay-evidence/apk-cache/<qq-music-apk> \
  ~/ushareiplay-evidence/apk-cache/<soul-apk>
```

The final camera acceptance check is that `dumpsys media.camera` reports two
devices with `Facing: Front` and `Facing: Back`, followed by Soul's own face
recognition flow. A camera preview alone is not sufficient if the phone is not
visible to the Emulator webcam list.

## Human Boundary

The harness owns AVD creation, root and remount setup, system changes, third-party component installation, APK extraction and installation, module or library activation, service restarts, test execution, evidence collection, retry, rollback, and destruction/recreation.

Human action is permitted only for:

1. macOS or Android authorization prompts that the automation identity cannot approve;
2. Soul login, CAPTCHA, device verification, or account risk controls;
3. the final Soul two-account listening check.

QQ Music login is not a prerequisite. Free or guest playback is sufficient for the final source check, and the `Synthetic Playback Source` is used before that check.

No acceptance step may depend on the operator manually deploying or debugging the Android runtime.

## Required Acceptance Gates

### Gate 0: Harness Repeatability

The harness provisions a clean rooted AVD, installs the fixed APK set, applies the selected experiment, runs a health check, collects evidence, and can repeat the operation after interruption without manual cleanup. A failed run can be safely destroyed and recreated.

Required evidence:

- machine-readable environment manifest;
- exact emulator, system image, APK, and experiment component versions;
- command logs and exit statuses;
- root/remount and Android service health checks.

### Gate 1: AudioRecord Probe and Microphone Injection

An independent `AudioRecord Probe` uses `VOICE_COMMUNICATION`, 16 kHz, mono, PCM 16-bit, and continuous `AudioRecord.read()`. A deterministic test file is configured as the injection source.

Positive run requirements:

- the probe receives the deterministic source fingerprint rather than the host microphone;
- native hook or system substitution logs show the target recording path was reached;
- raw source and captured PCM, hashes, metadata, and analysis JSON are retained.

Negative run requirements:

- injection is disabled or the source file is absent;
- the captured result fails the source fingerprint or amplitude criteria.

Gate 1 proves only that Android-side microphone substitution works for the probe. It does not prove Soul compatibility.

### Gate 2: Soul Hook Gate

Using the same deterministic source and the same automated experiment, Soul must be shown to consume the substituted microphone frames.

Required positive and negative evidence:

- Soul process loads the selected injection mechanism and reaches its recording path;
- a second Soul account hears the deterministic test audio;
- disabling the mechanism or clearing its source stops the deterministic audio;
- emulator host microphone input is disabled during the test to exclude accidental acoustic loopback.

If Gate 2 fails after one automated compatibility diagnosis, the PhantomMic-style app-process branch is stopped. The harness may continue with a system-level or HAL branch, but it must not silently claim Soul support.

### Gate 3A: Synthetic Live Audio Bridge

Only after Gates 1 and 2 pass, replace the deterministic file source with a `Synthetic Playback Source` that emits deterministic PCM through Android's normal playback path. This isolates the bridge from QQ Music catalog, login, and app-specific behavior.

Required evidence:

- no intermediate recording file is used in the steady state;
- QQ Music pause and resume recover automatically;
- a 30-minute run has no crash, permanent interruption, or unbounded buffer growth;
- the bridge does not accumulate unbounded delay or drift;
- the actual delay is recorded but is not itself a failure criterion.

The two-account Soul listening check must confirm that the synthetic playback is heard and unrelated Android playback is excluded.

### Gate 3B: QQ Music Source Compatibility

After Gate 3A passes, replace the synthetic player with currently playing QQ Music PCM. Guest or free playback is sufficient; no account login is required. The bridge must target QQ Music only; Soul audio, notifications, and other application playback must not be injected.

Required evidence:

- QQ Music playback reaches the same bridge path without a recording file;
- QQ Music pause and resume recover automatically;
- the two-account Soul listening check confirms QQ Music is heard;
- synthetic-player and QQ Music reports remain separate.

### Gate 4: Existing Objective Audio Verification

The candidate must also pass the repository's independent positive and negative audio verification contract: deterministic multi-tone playback, captured microphone frames, fixed amplitude and fingerprint thresholds, raw PCM, hashes, and a machine-readable report.

This gate must be run with the candidate enabled and disabled. A successful application launch or hook log is not a substitute for captured-signal evidence.

### Gate 5: UShareIPlay Integration

The candidate must connect through the existing Appium and local configuration boundary without changing Soul or QQ Music automation logic. A clean harness run must support the normal UShareIPlay workflow, and macOS default input and output devices must remain unchanged before, during, and after the run.

## Candidate Order

The harness should attempt candidates from lower to higher system coupling:

1. An independently implemented PhantomMic-style file injection path, using the project only as a behavioral reference because the upstream repository has no license.
2. A rooted Frida app-process file injection path, using fixed Android 30 symbol offsets and a pinned ARM64 Frida server.
3. A no-root or reduced-root app-process variant if the emulator supports it.
4. An app-process `Live Audio Bridge` that captures QQ Music output and supplies Soul recording frames through a local IPC path.
5. A rooted Android system route using AudioPolicy, AudioFlinger, or a virtual input/HAL modification.
6. A custom emulator host-audio backend, only if the Android-side candidates fail.

Each candidate must identify its own evidence directory and must not overwrite a previous candidate's report.

## Stop and Promotion Rules

- A candidate that fails its required negative control is invalid even if its positive run sounds plausible.
- A candidate that fails Gate 1 is not used for Soul testing.
- A candidate that fails Gate 2 is not extended into a Live Audio Bridge.
- Passing Gate 3A or 3B without Gates 4 and 5 does not make the candidate production-ready.
- Waydroid remains the supported backend until Gates 0 through 5 pass on a reproducible clean run.

## Evidence Layout

Every run stores an immutable directory containing:

- `environment.json`;
- `commands.log` and service or hook logs;
- source and capture PCM files;
- SHA-256 manifest;
- analyzer report for positive and negative runs;
- candidate configuration and AVD properties;
- a final gate status (`passed`, `failed`, or `blocked-on-human-auth`).

The harness must print the evidence directory and the first failed gate on exit.

## Current Gate Evidence

The first rooted candidate has passed Gate 0 and the automated portion of Gate 1 on the local Apple Silicon host:

- AVD `ushareiplay-audio-root`, Android 30 `google_apis;arm64-v8a`, Emulator 36.1.9.0.
- `adb root`, writable overlayfs for system partitions, and `uid=0` confirmed; Android guest SELinux remains Enforcing.
- QQ Music `20.4.0.5` and Soul `6.31.0` were extracted from APK Source Device `554b4e4745413498` with retained SHA-256 manifests.
- Frida server `17.17.0` ARM64 was downloaded with SHA-256 `09d1fad867b27d69562a79289f4c412e85867f5d38ab72877036ed35e4223021`.
- Probe positive capture: peak `0.549913`, correlation `0.9999999994`, SNR `89.2 dB`, active tone frames `7/4`.
- Probe disabled negative capture: peak `0.000122`, active tone frames `0/4`; it failed amplitude and tone fingerprint as required.

These results prove the rooted Android-side Microphone Injection candidate for the AudioRecord Probe only. Gate 2 Soul compatibility, Gates 3A/3B Live Audio Bridge, Gate 4 objective promotion verification, and Gate 5 UShareIPlay integration remain open.

The Soul hook handoff is now automated by `scripts/rooted_emulator_harness.py soul-hook`. It grants the experiment permissions, pushes the deterministic source, force-stops Soul, uses Frida spawn injection to avoid Soul's startup process-replacement race, collects the activity and logcat snapshots, and writes `gate-2` as `blocked-on-human-auth` until the operator completes login and the two-account listening check. A recent 20-second run retained at `~/ushareiplay-evidence/rooted-emulator/soul-gate-20260819T235000Z-stability` installed the hook successfully and retained the same Soul PID after the observation window; it observed no `AudioRecord::obtainBuffer` calls while Soul was still on the login screen. This is a compatibility handoff, not a positive Soul audio result. Earlier attach-mode retries exposed a startup race and are retained as diagnostic evidence, not as a conclusive Soul incompatibility result.

To resume the handoff after the unavoidable login step, run the same `soul-hook` command with a fresh evidence directory. The command is idempotent for the disposable AVD and leaves all host audio defaults untouched. The app-process branch must not advance to the Live Audio Bridge until the positive and disabled Soul listening controls are recorded.

The first Gate 3A bridge primitive is also implemented as verifier mode `playback_capture`. It requests the Android MediaProjection authorization, starts a project-owned foreground service for the capture lifetime, plays the deterministic source with `AudioTrack`, and captures only the verifier UID with `AudioPlaybackCaptureConfiguration`. On the rooted AVD the run completed with source and capture artifacts under `~/ushareiplay-evidence/rooted-emulator/playback-capture-20260819T235616Z`; analysis returned correlation `1.0`, SNR `120 dB`, peak `0.549896`, active tones `7/4`, and tone-ratio error `0.00000293`. This proves Android playback capture, but it is not yet a Soul bridge and does not advance Gate 3A until Gate 2 passes.

The current system-route inspection records `audio.primary.default.so` with the Ranchu audio service and a separate `Remote Submix` module. The primary policy maps the built-in microphone only to the primary input; it does not route media output into that input. The next system-level candidate is therefore a guest-only AudioPolicy/HAL route that feeds a selected QQ Music playback capture into the microphone path. No macOS audio device or default was changed. The unlicensed PhantomMic repository remains a behavioral reference only.
