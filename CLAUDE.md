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

Current phase: **implementation**. Milestones M0 (repository bootstrap) and M1 (walking skeleton with notifications) are written; M1 passed its acceptance run on the test cluster on 2026-10-04. The next step is M2 in `ROADMAP.md`.

### Where things are

| Document | Read it when |
| --- | --- |
| `PROJECT.md` | You need the purpose, the audience or the scope of version 1 |
| `REQUIREMENTS.md` | You implement or test something; every requirement has a stable ID |
| `ARCHITECTURE.md` | You touch the design; it describes the current state |
| `docs/adr/README.md` | You want to know why something is the way it is |
| `docs/research/` | You need the evidence and the sources behind a decision |
| `docs/check-catalog.md` | You work on checks or thresholds |
| `ROADMAP.md` | You plan the next step |
| `OPEN-QUESTIONS.md` | Something is unclear; it may already be listed there |

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
