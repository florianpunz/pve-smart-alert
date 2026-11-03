# ADR 0042: Short code comments

- Status: Accepted
- Date: 2026-11-03
- Decided by: the maintainer

## Context

Comments had grown into long blocks. They repeated the reasoning of a decision record, restated what the code says, and carried dates, milestones and host names. That duplicates facts that live in one place and makes every comment a second copy that goes stale: a changed threshold or a renamed function leaves the prose behind, and a reader cannot tell which of the two is current.

The maintenance rules in [CLAUDE.md](../../CLAUDE.md) already say that each fact has one home and that documents are kept current. They did not say the same for comments, so comments drifted.

## Decision

A comment describes what the code does now. It never describes a planned fix, a milestone or a date. One style applies to the shipped code in this repository, in every language: `src/`, `libexec/`, `systemd/`, `scripts/`, `debian/` and `config/config.toml`. Test code, the CI workflows and `config/config.reference.toml` are out of scope: a test uses hosts, dates and question IDs as data, and the reference configuration is user documentation (ADR 0011).

1. A comment says **why** or **warns**. It never restates what the code says.
2. Inline and block comments are one or two lines, with a hard limit of three.
3. A docstring has one summary line. Its body carries only contract details that are not obvious, such as a return value, a raised exception or a side effect, in at most four lines. A module docstring states the purpose in at most five lines, then one line of references.
4. The file header of a shell, Perl or systemd file is at most five lines.
5. Longer reasoning lives in an ADR or a document and is referenced by identifier: `ADR 0010`, `FR-302`, `NFR-08`, `Q-T1`, `Research 03`, `ARCHITECTURE.md section 10`. Code carries no Markdown link.
6. A warning starts with "Do not ..." or "Keep in sync with ..." and gives the reason in a few words.
7. Units and limits are named: °C, %, s, min, attribute IDs, exit bits.
8. No plans, milestones, dates or host names. Evidence is referenced as `Research NN`.
9. `Q-` is used only for a question that is still open in [OPEN-QUESTIONS.md](../../OPEN-QUESTIONS.md). An answered question points to where the answer lives.
10. An external source is named by function and version, not by line number.
11. No `TODO`, `FIXME` or `NOTE` marker. Open work goes to [ROADMAP.md](../../ROADMAP.md) or [OPEN-QUESTIONS.md](../../OPEN-QUESTIONS.md).
12. Comments start with `#`, not with `#:`. A fact is stated once: a comment does not repeat its docstring.

## Consequences

- A comment that needs more than the limit moves its reasoning to an ADR or a document and keeps a reference.
- A finding that needs a code change is written as the honest comment of the current behavior, and the fix is listed in [ROADMAP.md](../../ROADMAP.md).
- Review reads comments against these rules.

## Revisit when

- A comment limit turns out to hide a contract that a caller needs, or a language gets a documentation convention that the project adopts.
