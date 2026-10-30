# ADR 0035: Purge removes the directory of the Python package

- Status: Accepted
- Date: 2026-10-30
- Decided by: the maintainer
- Supersedes: the purge paths of [ADR 0013](0013-packaging-and-installation.md)

## Context

[ADR 0013](0013-packaging-and-installation.md) lists what the `postrm` removes on purge: the configuration under `/etc/pve-smart-alert/` and the state under `/var/lib/pve-smart-alert/`; the runtime directory `/run/pve-smart-alert/` was added later ([ROADMAP.md](../../ROADMAP.md), M5). Everything under `/usr` belongs to dpkg and was left to it.

That held until the host checks of `0.5.0~dev4` on `pve1` on 2026-10-18. The first purge left `__pycache__` directories with byte code of `__init__`, `model` and `parsers` below `/usr/share/pve-smart-alert/pve_smart_alert/`, and dpkg warned that the directory was not empty. The launcher writes no byte code (`-B` and `PYTHONDONTWRITEBYTECODE`, [ADR 0003](0003-implementation-language.md)), and no installed file apart from the launcher runs Python, so the cache came from something else that ran Python against the installed tree. Where it came from was not found.

dpkg removes a directory only when it is empty. A file in a directory the package owns keeps the directory alive when dpkg removed the package's own files: nothing can clean it up except the maintainer script, and "nothing of the tool is left after a purge" (M5 step 7) is no longer true.

## Options considered

1. **Leave it.** `apt purge` leaves `/usr/share/pve-smart-alert` behind whenever anything wrote into it. The acceptance step of M5 fails and the user has to remove the directory by hand.
2. **Remove only what was written there, then the empty directories.** The maintainer script cannot tell a byte code cache from a site patch, so "only what was written there" means the `__pycache__` trees, followed by `rmdir` on the directories that are then empty. Narrower, but it still decides by name which foreign files in the tool's own directory may go, and the next kind of stray file needs another entry.
3. **Remove the whole directory of the package on purge.** One rule for the path the package owns.

## Decision

Option 3.

- On purge, the `postrm` removes `/usr/share/pve-smart-alert/` together with `/etc/pve-smart-alert/`, `/var/lib/pve-smart-alert/` and `/run/pve-smart-alert/`.
- At the time `postrm` runs with `purge`, dpkg has already removed every file of the package, so whatever is in the directory was not installed by this package. Removing the directory therefore removes foreign content as well; that is the accepted cost of the one rule, and it is bounded by the path that belongs to the tool.
- On `remove`, nothing is removed, as before.
- The package test plants a byte code cache below the installed directory before the purge and fails if the directory survives, so the rule is checked in CI and not only on a host ([ADR 0016](0016-test-strategy.md), layer 4).

This supersedes the list of paths that [ADR 0013](0013-packaging-and-installation.md) gives for the purge; the rest of that record stands. It extends the footprint of [ADR 0012](0012-read-only-and-coexistence-with-smartd.md) for the purge: a purge removes the directory of the tool with everything in it, including a file that the package did not install.

## Consequences

- `apt purge pve-smart-alert` leaves nothing of the tool, whatever wrote into its directory.
- A file that an administrator or another package placed below `/usr/share/pve-smart-alert` is removed by the purge without a question. Nothing else installs there today; a package that wants to must not.
- The directory of the Python package is now named in the maintainer scripts, in ARCHITECTURE.md and in CONTRIBUTING.md, and the path is part of the packaging contract.

## Revisit when

- Another package or a supported integration needs to put files into `/usr/share/pve-smart-alert`.
