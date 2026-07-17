# UShareIPlay

UShareIPlay controls Soul App party rooms and QQ Music playback through chat-driven automation. This glossary names the domain concepts used when discussing behavior across room, music, user, and timer workflows.

## Language

**Seat Management**:
All behavior around Soul App party seats, including reservation policy, occupancy checks, automatic seating on entry, taking seats, removing occupants, and preparing seat UI state when another workflow depends on the seat panel.
_Avoid_: Seat command, seating helper, seat UI layer

**Command Execution**:
All behavior that turns runtime queue entries or scanned chat rows into command outcomes, including command detection, normalization, routing, execution, and response delivery.
_Avoid_: Command parser, queue drainer, chat command handler

**Event Processing**:
All behavior that describes and reacts to the current app screen, including page-source readiness, screen classification, event priority, UI-busy suppression, and unknown-page recovery.
_Avoid_: Event loop, page-source helper, fallback navigation

**Chat Intake**:
The pure classification and normalization boundary for raw chat text and runtime queue grammar. It turns a single raw chat line into a frozen, typed result (user enter/return, keyword mention, command, or plain chat) and expands `;`-separated queue text with `{user_name}` substitution, silent-prefix detection, and private-reply detection. Chat Intake has no side effects and owns the regex families so that CommandManager, MessageManager, MessageContentEvent, and KeywordManager do not duplicate them.
_Avoid_: Message parser, chat classifier, command matcher
