## 1. Sync openspec/specs/ from archived changes

- [x] 1.1 Create `openspec/specs/` directory and sync delta specs from `gift-fallback-yellow-duck` archive
- [x] 1.2 Sync delta specs from `timer-config-to-db` archive
- [x] 1.3 Sync delta specs from `local-config-override` archive

## 2. Clear old docs

- [x] 2.1 Delete all existing files in `docs/`

## 3. Write capability docs

- [x] 3.1 Write `docs/music.md` (QQMusicHandler, MusicManager, music commands)
- [x] 3.2 Write `docs/room.md` (PartyManager, SoulHandler room ops, room commands)
- [x] 3.3 Write `docs/users.md` (UserManager, AdminManager, SeatManager, user commands)
- [x] 3.4 Write `docs/timers.md` (TimerManager, TimerCommand, Timer model/DAO)
- [x] 3.5 Write `docs/config.md` (ConfigLoader, config.yaml, config.local.yaml)
- [x] 3.6 Write `docs/system.md` (AppController, AppHandler, CommandManager, crash recovery, DB)

## 4. Rewrite README

- [x] 4.1 Rewrite `README.md` with overview, quick start, full command table, and capability index

## 5. Extend opsx:archive skill

- [x] 5.1 Add README + docs check step to `opsx:archive` skill (after spec-sync, before mv): read change impact, intersect with `covers:` frontmatter, prompt user to confirm or skip updates
