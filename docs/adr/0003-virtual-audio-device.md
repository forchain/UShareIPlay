# Virtual Audio Device uses host loopback with a disposable root fallback

UShareIPlay replaces the physical Android audio-loopback target with a Play Store ARM64 AVD whose playback is returned through the host audio input, using BlackHole 2ch on macOS and PipeWire on Linux. This is preferred over modifying Android audio internals because Android Emulator officially supports host microphone input; a separate, rootable Google APIs AVD is created only after retained positive and negative-control evidence proves that this supported route fails.
