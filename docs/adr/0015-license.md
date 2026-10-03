# ADR 0015: License AGPL-3.0-or-later

- Status: Accepted
- Date: 2026-10-03

## Context

The project is open source from the first commit and needs a license before code or contributions exist, because changing it later requires the consent of every contributor.

Facts that bear on the choice:

- Proxmox VE, whose Perl module the notify bridge loads, is licensed under the GNU Affero General Public License, version 3 or later (`debian/copyright` of `pve-manager`).
- smartmontools is licensed under the GNU General Public License, version 2 or later (SPDX identifier in its source files). Its drive database contains knowledge about vendor-specific attributes that could be useful to reuse.
- Scrutiny, whose failure-rate table and recorded outputs are useful to reuse, is under the MIT license.
- The tool is a host-local program. It offers no network service, so the network clause that distinguishes the AGPL from the GPL has no practical effect on its users.
- Everyone who can use the tool already runs AGPL-licensed software on the same host.

This record is an engineering decision, not legal advice.

## Options considered

| License | For | Against |
| --- | --- | --- |
| MIT | Simplest. Common for community scripts. Anyone can reuse snippets. | Code from Proxmox VE or smartmontools cannot be copied into the project. Forks can be closed. |
| Apache-2.0 | Permissive with a patent grant. | Same reuse limits as MIT. Not compatible with GPL version 2 only code. |
| GPL-3.0-or-later | Copyleft. Can take code from smartmontools. | Taking code from Proxmox VE (AGPL) would still raise questions. |
| **AGPL-3.0-or-later** | Same license family and version as Proxmox VE. Code from Proxmox VE, from smartmontools (through its "or later" option) and from MIT projects can be reused. No doubt about loading Proxmox VE's modules. Improvements stay open. | Some organizations avoid AGPL software on principle. Does not apply to this audience, see above. Reuse of PVE SMART Alert code in permissively licensed projects is not possible. |

## Decision

- The project is licensed under the **GNU Affero General Public License, version 3 or (at the option of the user) any later version**. SPDX identifier: `AGPL-3.0-or-later`.
- Every source file starts with an SPDX license identifier line. The full text is in `LICENSE`.
- Contributions are accepted under the same license ("inbound equals outbound"). No contributor license agreement.
- Third-party material is recorded:
  - Data derived from Scrutiny (MIT) is marked in the file that contains it, and the MIT notice is kept in `THIRD-PARTY-NOTICES.md`.
  - Every fixture has its origin and license in `tests/fixtures/SOURCES.md`.
- The copyright line names the maintainer. The name is recorded in `PROJECT.md`.

## Consequences

- The project can borrow from the code bases it builds on without license friction.
- Anyone who distributes a modified version must offer its source under the same license.
- The license can be changed later only with the consent of all contributors. The maintainer should confirm the choice before the first external contribution is merged; until then a change is free.
- Projects under permissive licenses cannot copy PVE SMART Alert code. They can still use its documentation of thresholds and its fixtures, as far as the fixtures' own licenses allow.
- Proxmox is a registered trademark of Proxmox Server Solutions GmbH. The project states in its README that it is not affiliated with or endorsed by that company.

## Revisit when

- The maintainer prefers a permissive license. This is cheapest before the first external contribution.
- The project is proposed for inclusion in a collection that requires a specific license.
