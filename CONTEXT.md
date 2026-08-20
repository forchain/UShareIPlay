# UShareIPlay

UShareIPlay controls Soul App party rooms and QQ Music playback through chat-driven automation. This glossary names the domain concepts used when discussing behavior across room, music, user, and timer workflows.

## Language

**Seat Management**:
All behavior around Soul App party seats, including reservation policy, occupancy checks, automatic seating on entry, taking seats, removing occupants, and preparing seat UI state when another workflow depends on the seat panel.
_Avoid_: Seat command, seating helper, seat UI layer

**Room Name**:
The combined Soul App party room name `{theme}｜{title}`, its shared cooldown, pending theme/title state, the single UI write, and notice restoration. Owned by `RoomNameManager`.
_Avoid_: ThemeManager, TitleManager (legacy adapters)

**Command Execution**:
All behavior that turns runtime queue entries or scanned chat rows into command outcomes, including command detection, normalization, routing, execution, configured command retries, and response delivery.
_Avoid_: Command parser, queue drainer, chat command handler

**Event Processing**:
All behavior that describes and reacts to the current app screen, including page-source readiness, screen classification, event priority, UI-busy suppression, and unknown-page recovery.
_Avoid_: Event loop, page-source helper, fallback navigation

**Chat Intake**:
The pure classification and normalization boundary for raw chat text and runtime queue grammar. It turns a single raw chat line into a frozen, typed result (user enter/return, keyword mention, command, or plain chat) and expands `;`-separated queue text with `{user_name}` substitution, silent-prefix detection, and private-reply detection. Chat Intake has no side effects and owns the regex families so that CommandManager, MessageManager, MessageContentEvent, and KeywordManager do not duplicate them.
_Avoid_: Message parser, chat classifier, command matcher

**E2E Session**:
One owned run of UShareIPlay validation, including the service and every helper process that can contend for its Android/Appium target.
_Avoid_: Test PID, runner process

**Device Lease**:
The machine-wide ownership record that grants one E2E Session exclusive use of a shared Android/Appium target.
_Avoid_: Lock file, local PID

**Virtual Audio Device**:
An Android Emulator instance that replaces the physical Android target for UShareIPlay and supplies a playback-to-microphone audio path.
_Avoid_: Emulator, virtual machine, test device

**Rooted Emulator Experiment**:
A disposable candidate Virtual Audio Device used to test Android-side microphone substitution with elevated Android privileges; it is experimental and is not the production backend.
_Avoid_: Rooted production emulator, modified host audio

**Rooted Emulator Harness**:
The idempotent automation boundary that provisions, modifies, exercises, diagnoses, and safely rebuilds a Rooted Emulator Experiment while retaining its evidence; manual deployment is outside this boundary.
_Avoid_: Setup notes, manual root procedure

**APK Source Device**:
An explicitly selected authorized Android device used only to extract version-pinned application APKs for a Rooted Emulator Experiment; its application data and credentials are out of scope.
_Avoid_: Production device, account mirror

**Acceptance Gate**:
A falsifiable stage boundary that must pass its required positive and negative evidence before the next audio implementation stage is attempted.
_Avoid_: Smoke test, subjective check

**Microphone Injection**:
Replacing the microphone frames observed by the target Android app with deterministic audio, without claiming that Android playback has been routed through the system microphone device.
_Avoid_: Audio loopback, speaker routing

**Rooted Process Hook**:
A guest-only native instrumentation mechanism attached to one Android application process to implement Microphone Injection; its success for an AudioRecord Probe does not establish Target App Verification.
_Avoid_: System audio route, host hook

**Live Audio Bridge**:
A continuous PCM path that carries currently playing QQ Music audio into the microphone frames consumed by Soul without an intermediate recording file; it prioritizes continuity and bounded buffering over low latency.
_Avoid_: Real-time bridge, file playback

**Synthetic Playback Source**:
A disposable Android player used to emit deterministic PCM through the normal playback path while validating a Live Audio Bridge independently of QQ Music login, catalog access, or app-specific behavior.
_Avoid_: Fake QQ Music, test recording file

**AudioRecord Probe**:
A small disposable Android test client that opens the microphone, records raw frames, and exposes deterministic artifacts for validating Microphone Injection independently of Soul's room and permission workflow.
_Avoid_: Soul test, production verifier

**Target App Verification**:
The separate confirmation that a candidate Microphone Injection route works inside Soul after the AudioRecord Probe has passed.
_Avoid_: Generic loopback proof

**Audio Loopback Verification**:
The first-stage black-box proof that audio generated by an Android app is captured through the Virtual Audio Device microphone. It requires a passing deterministic signal test, a failing no-loopback control, and retained raw artifacts; it is distinct from proving that Soul's production voice SDK uses that microphone.
_Avoid_: Soul audio verification, DSP smoke test

**Host Audio Loopback**:
The host-managed route that sends the Virtual Audio Device playback back to its host-microphone input. BlackHole 2ch is the macOS implementation; PipeWire is the Linux implementation.
_Avoid_: Audio HAL hook, rooted audio router, AVD system modification

**Root Fallback**:
Audio-routing work inside a disposable, rootable Virtual Audio Device after the supported Host Audio Loopback has failed with retained verification evidence. It never includes weakening the host operating system's security controls.
_Avoid_: Primary audio route, host system modification

**Natural Language Command Resolution**:
The intent translation boundary that resolves unstructured `@我` mentions into concrete commands or conversational replies via an LLM when no registered keyword matches. It enriches the prompt with the speaker's level, system command schemas, and playback context, enforces strict JSON schema extraction, and gracefully falls back to the default keyword on timeouts, parse failures, or disabled LLM state.
_Avoid_: Chatbot, AI agent, prompt helper

**One-Click Installer**:
The idempotent provisioning boundary and entry point (`install.sh`) that establishes a complete UShareIPlay runtime on Ubuntu Linux. It bootstraps system prerequisites, clones/updates the repository, provisions the Virtual Audio Device and Host Audio Loopback, installs application packages, configures Appium background service, and registers Persistent ADB Port Forwarding.
_Avoid_: Setup helper, install script, deploy tool

**Persistent ADB Port Forward**:
The host-level NAT DNAT/FORWARD routing mechanism and lifecycle supervisor that maps incoming host ADB traffic (port 5555) to the internal Virtual Audio Device container across container IP renewals, service restarts, and host reboots.
_Avoid_: Adb tunnel, port map helper, adb forwarder
