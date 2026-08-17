# Waydroid Virtual Audio Device

The supported backend is Ubuntu Linux with Waydroid and PipeWire. Android playback is sent to a dedicated PipeWire null sink, and that sink's monitor is exposed as the Android microphone input. This makes QQ Music (or any other Android player) available to Soul without changing a macOS host input device.

## Why This Backend

The standard Android Emulator was rejected as an audio backend. Its host-microphone path depends on the host default input and the standard `AudioRecord` path produced silence and Ranchu HAL input errors during the controlled test. BlackHole and Loopback do not remove that emulator limitation.

OrbStack was also rejected for the production deployment. Its Linux machine did not provide binderfs, `/dev/dri`, or a desktop Wayland session, and Waydroid cannot boot there reliably.

The recommended deployment is an ARM64 Ubuntu 24.04 VM in Parallels on Apple silicon. QQ Music and Soul are both ARM64 APKs, so this avoids the x86_64 host's ARM translation overhead. The VM should have at least 4 vCPUs and 8 GB RAM; the initial 2 vCPU/4 GB VM booted successfully but is under-provisioned for two active applications.

## Install And Open

Run these commands from the logged-in Wayland desktop user on the Ubuntu host. Do not run the UI command from an unrelated SSH user; Waydroid's session belongs to the graphical user.

```bash
scripts/waydroid_virtual_audio.sh prepare
scripts/waydroid_virtual_audio.sh open --loopback
```

`prepare` installs the official Waydroid repository, Waydroid, PipeWire PulseAudio compatibility, ADB tooling, binder support, and the correct Android image for the host architecture. `open --loopback` starts the Android session, creates the owned `ushareiplay_music_sink`, sets its monitor as the default input, and opens the Android UI.

The generic desktop entry starts the background session and may close immediately. To open the visible Android window manually:

```bash
waydroid show-full-ui
```

To launch installed applications directly:

```bash
waydroid app launch com.tencent.qqmusic
waydroid app launch cn.soulapp.android
waydroid app launch io.ushareiplay.loopback
```

On a shared Linux desktop, `open` without `--loopback` never changes PipeWire defaults. Use `route-start` only while the Android audio route is needed, then run:

```bash
scripts/waydroid_virtual_audio.sh route-stop
```

`route-stop` unloads the owned sink and restores the exact prior PipeWire default sink and source. No macOS input/output device is changed by this backend.

## Manual Acceptance Flow

1. Start Waydroid with `open --loopback`.
2. Install the official ARM64 QQ Music and Soul APKs.
3. Accept each app's first-run privacy prompts and grant microphone permission to Soul.
4. Log into QQ Music and start a song.
5. Open a Soul voice/chat room and join from a second Soul account.
6. Confirm the second account hears the QQ Music audio.
7. Run the Loopback Verifier for an independent signal-level check.

The verifier is the objective gate; subjective listening is only the final product-flow check.

## Objective Acceptance

The verifier plays a five-second 440 Hz plus 997 Hz signal through `AudioTrack` and records seven seconds through `AudioRecord`. The enabled route passes only when all conditions hold:

1. Peak amplitude is at least `0.05`.
2. At least four one-second frames contain every source-derived tone above 5% of its source level.
3. For multi-tone input, the median tone ratio differs from the source by no more than 15%.
4. The disabled-route negative control fails amplitude or the tone fingerprint.

On the verified Ubuntu host, the direct Android playback-to-Android microphone run produced peak amplitude `0.5498`, five active tone frames, and tone-ratio error `0.0000373`. The disabled route produced peak amplitude `0.0130` and zero active tone frames. Raw PCM, PipeWire snapshots, and SHA-256 values are retained under `~/ushareiplay-evidence/waydroid-acceptance-20260728`.

The Parallels ARM64 VM has passed image initialization, binder/container startup, GPU/audio device discovery, and native QQ Music/Soul launch. Its final positive/negative verifier run must be recorded separately before treating that VM as a completed acceptance environment.

## Performance Findings

The original 4-vCPU x86_64 Ubuntu host showed 33-52% CPU steal, a load average above 15, 2.9 GB swap usage, and high PipeWire error counts while QQ Music and Soul were active. The audio route was correct, but those host conditions caused audible delay and stutter. Moving to native ARM64 removes translation overhead; allocating sufficient VM CPU and memory is still required.
