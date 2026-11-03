# ADR 0036: Select a drive by the value the tool prints

- Status: Accepted
- Date: 2026-11-01
- Decides: the printed form of a drive identity, the value a selector compares, and the length limits of a printed value and a notification field

## Context

The identity of a drive is its model and serial number, normalized but otherwise as the drive reports them ([ADR 0005](0005-drive-discovery-and-identity.md)). A selector in `[[drive]]` or in `[discovery]` compares that value: the model as a glob pattern, the serial number exactly ([ADR 0024](0024-drive-selectors.md)). The notification fields `model` and `serial` are a stable interface ([ADR 0029](0029-notification-field-device-id.md), NFR-21), and a matcher compares them.

The tool does not print a drive string as it is. Control and format characters are replaced by a space, whitespace is collapsed and the value is cut (ARCHITECTURE.md section 14). Three consequences were found in the security review of milestone M7:

1. A model such as `ACME\x01X 8TB` is printed as `ACME X 8TB`. A selector copied from `scan` compares against the identity and matches nothing; if another drive really is `ACME X 8TB`, the copied rule selects that drive instead.
2. A value longer than the limit is cut without a mark, in `scan` and in a message. A selector copied from a cut value never matches.
3. The limit of a notification field is 128 characters, the limit of printed text 200. A serial of 150 characters is shown in full in the body but cut in the field, so a matcher written from the body never matches. A model or serial of control characters only cleans to nothing, and the field was left out entirely, so no matcher could select the drive at all.

The identity must not change. It is the key of the state ([ADR 0007](0007-state-storage.md)): a build that normalized it differently would treat every affected drive as missing and create a new record, with a false missing notification, a new first-run summary and reset baselines.

## Options considered

1. **Normalize the identity as it is printed.** The copied value would match. Rejected: it changes the state key of every drive that reports a control character, needing a migration, and it merges two drives that differ only in such a character, so one rule would select both.
2. **Match selectors against the printed form.** The copied value would match, and the identity stays as it is. Rejected for the same ambiguity in the selector, and because a printed form depends on the limit, so the meaning of a rule would change when the limit does.
3. **Print a machine-usable form next to the human one.** The human output stays readable, and the exact value is printed where a user copies from. The identity and the state stay untouched.

## Decision

Option 3, with these rules:

- The identity stays as [ADR 0005](0005-drive-discovery-and-identity.md) defines it, normalized but not cleaned. No state migration is needed and no drive changes its record.
- A printed string is cleaned and cut as before. A value that was cut carries the mark `…`, in `scan`, `status`, `check --dry-run` and in a message.
- The limit of a notification field is the same 200 characters as that of printed text, instead of 128, so that the body and a matcher see the same value up to the cut. A field that cleaning would leave empty carries the value as an escaped TOML string instead of being left out, so that a matcher can still select the drive. A field is still absent where its absence means something, such as `device-id` for a drive read without a pass-through type.
- When the printed form of the model or the serial number differs from the identity — because a control or format character was replaced, or because the value was cut — `pve-smart-alert scan` prints one additional line for the drive: `Selector:` followed by the value as a TOML string, such as `model = "ACME\u0001X 8TB"`. That line is exactly what is written into `[drive]` or `[discovery]`, and it is the only form the tool prints that is meant to be copied into the configuration. It is cut at the same limit as every other printed value and carries the mark when it is; a value longer than the limit is selected with a model wildcard.
- A lone surrogate, which a string of a drive can contain, cannot be written in TOML at all. Such a drive is selected by a model wildcard; the exact line is still printed for the serial number and for the parts of the model that can be written.
- A value that is printed in full and contains no replaced character gets no selector line; `scan` remains what it is for every healthy drive.

## Consequences

- A selector can always be derived from the output of the tool, also for a drive whose model or serial number holds a character the tool does not print.
- `scan` grows by one line for a drive whose printed identity differs from the stored one. The line names the selector kind, so it can be pasted as it is.
- A matcher on `model` or `serial` sees up to 200 characters instead of 128. A value between 129 and 200 characters that used to be cut in the field is now complete; no existing rule stops matching.
- The mark `…` also appears on a real value that ends with that character. The selector line tells the two apart.
- A notification field for a model or serial number of control characters only is present with an escaped value. A matcher for it has to be written from the selector line, because such a value cannot be typed.
- Two drives whose printed forms are equal are still told apart by their selector lines, and both keep their own state record.

## Revisit when

- A user reports a model or serial number for which the selector line is not enough, such as one with a lone surrogate that has to be selected exactly.
- The notification system documents a length limit for the value of a metadata field.
