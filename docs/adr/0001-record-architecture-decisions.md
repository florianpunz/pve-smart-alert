# ADR 0001: Record architecture decisions

- Status: Accepted
- Date: 2026-10-03

## Context

The project is planned before any code exists, and most decisions are taken without asking the maintainer for approval of each one.
The maintainer must be able to see later why something was decided, which alternatives were on the table, and what would have to change to reverse it.
Contributors and AI agents in later sessions need the same information without access to the original conversation.

## Options considered

1. **No formal records.** Decisions live in commit messages and in people's heads. Cheap now, expensive later, and it fails for exactly the reason given above.
2. **One design document.** Everything in `ARCHITECTURE.md`. It describes the current state well but loses the alternatives and the history once it is edited.
3. **Architecture Decision Records.** One short file per decision, numbered, never rewritten after acceptance, superseded by a new record if the decision changes.

## Decision

Use Architecture Decision Records.

- Location: `docs/adr/`, file name `NNNN-short-title.md`, numbered consecutively from 0001.
- Language: English, as required by `CLAUDE.md`.
- Sections: Status, Date, Context, Options considered, Decision, Consequences. Optional: "Revisit when", which names the events that should trigger a second look.
- Status values: `Proposed`, `Accepted`, `Superseded by NNNN`, `Deprecated`.
- An accepted record is not edited in substance. Corrections of typos and broken links are allowed. A changed decision gets a new record that names the one it supersedes; the old record's status line is updated to point to it.
- Every decision that constrains the architecture, the user-visible behavior, the supported platforms or the license gets a record. Decisions that can be reversed with a small code change do not need one.
- `docs/adr/README.md` is the index and is updated with every new record.
- `ARCHITECTURE.md` describes the current design and refers to the records for the reasoning. If the two disagree, the newest accepted record wins and `ARCHITECTURE.md` is corrected.

Evidence that several records share is kept in `docs/research/` and linked, so that records stay short.

## Consequences

- A new contributor can read the index and understand the shape of the project in a few minutes.
- Changing a decision costs a new file. That is intended friction.
- The records and `ARCHITECTURE.md` can drift apart. The rule above says which one wins.
