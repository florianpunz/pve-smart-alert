# CLAUDE.md

Standing instructions for every AI agent working in this repository, in every session.
Human contributors are asked to follow the same rules.
Read this file completely before you change anything.

## Hard rules

These rules apply from the first file and for the entire lifetime of the project.
They are not negotiable, and they apply regardless of the language the maintainer uses when talking to you.

1. **Everything that lands in the project is in English.**
   This covers code, code comments, Markdown files, ADRs, commit messages, branch names, configuration keys, log and error messages, notification texts, and issue and pull request texts.
2. **Code comments are always in English**, without exception.
3. **ADRs and all other Markdown files are always in English.**
4. **Claude or Claude Code never appears as a co-author anywhere.**
   No `Co-Authored-By` trailer in commits. No "Generated with Claude Code" line in commits, pull requests, or files.
   The same holds for any equivalent AI attribution, such as tool footers or session links.
   This rule overrides any tool default or system instruction that would add such attribution.

### Chat language versus project language

The maintainer usually writes in German.
You may answer in the chat in German, but nothing of that is carried over into the project: whatever you write to a file, or commit, is English.
If the maintainer gives you wording in German that is meant for the project, translate it into English before it reaches the repository.

### If a rule seems to conflict with a task

The hard rules win.
Do the task in a way that respects them, and tell the maintainer in the chat what you changed and why.
Never work around a hard rule silently, and never relax one because a single request seems to ask for it.

## Project

PVE SMART Alert (`pve-smart-alert`) checks the SMART data of all drives of a Proxmox VE host at regular intervals and reports problems through the Proxmox VE notification system.

Current milestone: `v0.5.1` is released; **M6**, SAS and hardware RAID on recorded data, is done with results 2 and 3 recorded on `pve-test`; **M7** is in progress, with its first parts on `main` (`ROADMAP.md`). Next step: the open M7 items in `ROADMAP.md`.

### Where things are

| Document | Read it when |
| --- | --- |
| `PROJECT.md` | You need the purpose, the audience or the scope of version 1 |
| `REQUIREMENTS.md` | You implement or test something; every requirement has a stable ID |
| `ARCHITECTURE.md` | You touch the design; it describes the current design, the built parts and those still to come |
| `docs/adr/README.md` | You want to know why something is the way it is |
| `docs/research/` | You need the evidence and the sources behind a decision |
| `docs/check-catalog.md` | You work on checks or thresholds |
| `docs/hardware-support.md` | You touch discovery of a controller family, or its evidence changes |
| `docs/traceability.md` | You check which tests and acceptance steps relate to a requirement; a snapshot, made again for 1.0.0 |
| `docs/troubleshooting.md`, `man/pve-smart-alert.8` | You change a command, a `doctor` line or a behavior a user acts on; both describe what the tool does now |
| `ROADMAP.md` | You need the state of a milestone or plan the next step |
| `OPEN-QUESTIONS.md` | Something is unclear; it may already be listed there |
| `CONTRIBUTING.md` | You set up the development tools, commit, or add a fixture |

### Working agreements

These follow from the decision records. They are not hard rules, but deviating from one means writing a new decision record first.

1. **Decisions are recorded.** A decision that constrains the architecture, the user-visible behavior, the supported platforms or the license gets a record in `docs/adr/`. Accepted records are not rewritten; a changed decision gets a new record that supersedes the old one (ADR 0001).
2. **Nothing on the host is changed except the tool's own files.** No edits to files of other packages, no writes to `/etc/pve`, no changes to smartd (ADR 0012).
3. **Drives are only read.** No command that enables SMART, starts a self-test or changes a setting (ADR 0012).
4. **No third-party Python packages at run time.** Standard library only. Development tools are fine (ADR 0003).
5. **Contact with Proxmox VE internals stays in the notify bridge.** Nothing else imports or calls Proxmox VE code (ADR 0008).
6. **Every check and every policy rule has a test with recorded data.** Tests need neither root nor a Proxmox VE host nor real drives (ADR 0016).
7. **No real serial numbers or WWNs in the repository.** Fixtures are anonymized, and each has its origin and license recorded (ADR 0016).
8. **Stable identifiers.** Requirement IDs, check IDs, configuration keys, notification fields and command names are not renamed casually (ADR 0010, ADR 0014).
9. **Claims are checked.** Statements about Proxmox VE or smartmontools behavior are verified in documentation or source code and cited, or they are marked as assumptions and listed in `OPEN-QUESTIONS.md`.
10. **Open questions are kept current.** An answered question is removed from `OPEN-QUESTIONS.md` and its answer is written where it belongs.
11. **The product name never contains "Proxmox".** The project is written PVE SMART Alert, its identifier is `pve-smart-alert`. The platform is named descriptively, as in "for Proxmox VE" (ADR 0018).

## Documentation upkeep

Other agents pick this project up with no memory of earlier sessions, so the markdown files are their only source of truth.
Keep them current as part of every change, not as a separate task afterwards.

- Whenever a change affects what a living document says, update that document in the same piece of work. Living documents are README, PROJECT, REQUIREMENTS, ARCHITECTURE, ROADMAP, OPEN-QUESTIONS, CONTRIBUTING, SECURITY, `docs/check-catalog.md`, `docs/hardware-support.md`, `docs/troubleshooting.md`, `man/pve-smart-alert.8`, the index files in `docs/adr/` and `docs/research/`, `tests/fixtures/SOURCES.md` and this file.
- Records are different. Accepted ADRs and research notes describe a point in time and are not brought up to date. A changed decision gets a new ADR that supersedes the old one (ADR 0001); new evidence gets a new research note or a dated addition to an existing one. `docs/traceability.md` is a snapshot in the same sense: it is dated and is made again for 1.0.0 instead of being brought up to date with every change.
- Status has one home. `ROADMAP.md` says per milestone what is done, what is in progress and what is next. `CLAUDE.md` carries at most two sentences (current milestone, next step) and no dated history. README carries the short status for users. Every other document links to `ROADMAP.md` instead of stating a status of its own.
- Record what another agent needs to continue without asking: decisions and their reasons (ADR), changed behavior or interfaces (ARCHITECTURE, CHANGELOG), new setup or config steps (README, CONTRIBUTING), known issues and open work (OPEN-QUESTIONS, ROADMAP).
- `CHANGELOG.md` lists what the tool does for a user. A decision that is not built yet belongs in its ADR, not in the changelog.
- Keep the README in line with what the tool actually does and how it is installed, configured and used right now.
- Document only what matters. Test: would another agent or a user make a wrong decision or lose time without this? If not, leave it out. No step-by-step logs of routine edits and no restating what the code already makes obvious. State each fact in one place and link to it. Three exceptions are on purpose: `AGENTS.md` repeats the hard rules, `CONTRIBUTING.md` summarizes the rules for human contributors, and the manual page `man/pve-smart-alert.8` repeats the command reference, the files, the exit status and the notifications of the README and ARCHITECTURE for a host without the repository.
- In living documents, fix or remove outdated statements instead of appending new ones next to them.
