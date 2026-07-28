# Waydroid Virtual Audio Device

The supported audio backend is Ubuntu Linux with Waydroid and PipeWire. The macOS Android Emulator launcher remains available for manual application installation and Appium UI work, but it is not an audio-routing backend.

## Install And Open

Run these commands from the logged-in Wayland desktop user on the Ubuntu host:

```bash
scripts/waydroid_virtual_audio.sh prepare
scripts/waydroid_virtual_audio.sh open --loopback
```

`prepare` installs Waydroid, PipeWire PulseAudio compatibility, ADB tooling, and initializes the official Waydroid images. `open --loopback` starts the visible Android session and creates one owned PipeWire null sink, `ushareiplay_music_sink`. Android playback is sent to that sink, and its monitor is selected as Android microphone input.

Install QQ Music, Soul, and other Android applications in the visible Waydroid window. Set Android media volume high enough for the target application. The verified host used `STREAM_MUSIC` volume `15/15`.

`open` without `--loopback` never changes PipeWire defaults. On a shared Linux desktop, use `route-start` only while the Android audio route is needed, then run:

```bash
scripts/waydroid_virtual_audio.sh route-stop
```

This unloads the owned sink and restores the exact prior PipeWire default sink and source. No macOS input/output device is changed by this backend.

## Acceptance Evidence

The Android verifier plays a five-second 440 Hz plus 997 Hz signal through `AudioTrack` and records seven seconds through `AudioRecord`. The route passes only when all conditions hold:

1. The enabled run has a peak amplitude of at least `0.05`.
2. At least four one-second frames contain every source-derived tone above 5% of its source level.
3. For multi-tone input, the median tone ratio differs from the source by no more than 15%.
4. The disabled-route negative control fails amplitude or the tone fingerprint.

Correlation, SNR, and peak frequency are retained as diagnostics, but are not acceptance gates because Android's resampling and automatic gain control alter sample phase and SNR.

On the verified Ubuntu host, the direct Android playback-to-Android microphone run, with no host playback process, produced peak amplitude `0.5498`, five active tone frames, and tone-ratio error `0.0000373`. The disabled route produced peak amplitude `0.0130` and zero active tone frames. Raw PCM, PipeWire routing snapshots, and SHA-256 values are retained under the operator evidence directory.
