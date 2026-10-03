# ADR 0014: Repository structure

- Status: Accepted
- Date: 2026-10-03

## Context

The repository holds a Python package, a Perl script, templates, systemd units, Debian packaging, tests with a large set of recorded fixtures, and planning documents.
The structure should make it obvious where each kind of file belongs, keep the installed files separate from development files, and let the tests run from a checkout without installing anything.

## Options considered

1. **Flat layout**: the Python package in the repository root.
   Simple, but tests can import the checkout by accident instead of the built package, and the root fills up.
2. **`src` layout**: the Python package under `src/`.
   Standard practice. Clear separation between what is shipped and what is not.
3. **Split repositories** for tool, packaging and fixtures.
   Overhead without benefit at this size. A change to a parser and its fixtures belongs in one commit.

## Decision

One repository with a `src` layout.

```text
.
├── CLAUDE.md                 Binding rules for AI agents and contributors
├── AGENTS.md                 Pointer to CLAUDE.md for other agents
├── README.md                 Entry point for users
├── LICENSE                   AGPL-3.0-or-later (ADR 0015)
├── CHANGELOG.md              User-visible changes per release
├── CONTRIBUTING.md           How to contribute, including fixtures
├── SECURITY.md               How to report vulnerabilities
├── PROJECT.md                Purpose, audience, scope
├── REQUIREMENTS.md           Numbered requirements
├── ARCHITECTURE.md           Current design
├── ROADMAP.md                Milestones
├── OPEN-QUESTIONS.md         Unresolved points
├── pyproject.toml            Project metadata, tool configuration
├── Makefile                  Entry points: check, test, build, dev-install
├── src/
│   └── pve_smart_alert/      Python package
│       ├── cli.py            Command-line interface
│       ├── config.py         Loading and validation
│       ├── discovery/        Scan, probes, enrichment, filters
│       ├── collect.py        smartctl invocation
│       ├── parsers/          ata.py, nvme.py, scsi.py
│       ├── model.py          Snapshot, finding, drive identity
│       ├── checks/           Check catalog and evaluation
│       ├── policy.py         Notification planning
│       ├── state.py          State file handling
│       ├── render.py         Subject and body
│       └── transports/       pve_notify.py, mail.py
├── libexec/
│   ├── notify-bridge         Perl
│   └── report-failure        Shell
├── templates/                pve-smart-alert-*.hbs
├── systemd/                  Units
├── config/                   Shipped config.toml
├── debian/                   Packaging
├── scripts/                  install.sh, release helpers
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   │   ├── smartctl/         Recorded JSON, by protocol and controller
│   │   ├── scenarios/        Sequences of host states for end-to-end tests
│   │   └── SOURCES.md        Origin and license of every fixture
│   ├── fake-smartctl         Replays fixtures
│   └── perl-stubs/           Stub of PVE::Notify for the bridge test
├── docs/
│   ├── adr/                  Decision records
│   ├── research/             Evidence behind the decisions
│   ├── check-catalog.md      Checks and default thresholds
│   └── ...                   User documentation, added with the features
└── .github/workflows/        CI (name depends on the hosting platform)
```

Rules:

- Everything that ends up on a host comes from `src/`, `libexec/`, `templates/`, `systemd/` and `config/`. `debian/` only maps these to their installed paths.
- Planning documents stay in the repository root, as the maintainer specified. User documentation goes to `docs/`.
- Tests never need root, a Proxmox VE host or real drives. The path to smartctl and to the bridge is injectable for this reason.
- Fixtures are committed only in anonymized form, and every fixture has an entry in `SOURCES.md` ([ADR 0016](0016-test-strategy.md)).
- The check catalog document is generated from, or checked against, the definitions in `src/pve_smart_alert/checks/`, so that documentation and code cannot diverge unnoticed.
- Branch names, commit messages and all file contents are in English and carry no AI attribution (`CLAUDE.md`).

Conventions:

- Default branch `main`. Feature branches `feature/<topic>`, fixes `fix/<topic>`.
- Commit messages in the imperative, with an optional scope prefix such as `parsers:` or `docs:`.
- Versions follow semantic versioning. Check identifiers, configuration keys, notification fields and the command-line interface are the public interface.
- Releases are tagged `vX.Y.Z`.
- American English spelling in documents, identifiers and messages.

## Consequences

- A contributor can run the full test suite from a clone with only Python and the development tools.
- The mapping from repository to installed paths lives in one place, `debian/`.
- The fixture set will become the largest part of the repository. It stays in the main repository as long as its size is reasonable.
- The CI directory name assumes a particular hosting platform. It is the only platform-specific path and is easy to move.

## Revisit when

- The fixture set grows beyond what is comfortable in the main repository.
- A second distribution format is added.
