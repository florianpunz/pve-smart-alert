# ADR 0040: The line that switches the unsupported-controller notice off is valid TOML

- Status: Accepted
- Date: 2026-11-03
- Supersedes: [ADR 0031](0031-switching-tool-conditions-off.md) for the wording of the switch-off line only; every other part of the record governs as before

## Context

[ADR 0031](0031-switching-tool-conditions-off.md) prescribes that the notice `tool.unsupported_controller` names how it is switched off, and fixes the sentence to the letter:

> `switch this notice off with [checks."tool.unsupported_controller"] enabled = false`

That line is not TOML. A table header and a key-value pair cannot share a line, so a reader who copies it into `config.toml` gets a parse error instead of a switched-off condition:

```
Expected newline or end of document after a statement (at line 1, column 40)
```

The sentence cannot simply be split over two lines either. The notice is one string in a notification, and it is rendered as one sentence; the tool has no place to put a table header and a key beneath it without turning a message into a configuration file.

## Options considered

1. **Keep the sentence and add a note that it means two lines.** The notice would name a setting that the reader still has to assemble; the error would move from the parser to the reader.
2. **Write the setting as a dotted key: `checks."tool.unsupported_controller".enabled = false`.** TOML 1.0 allows dotted keys whose segments are quoted, and the configuration reads exactly the table that the two-line form sets. It is one line, it is valid TOML, and it can be pasted as it is.
3. **Name the table and the key in prose, without a line of TOML.** Readable, but not a setting; the reader still has to know where the table is.

## Decision

Option 2. The notice ends with:

> `switch this notice off with checks."tool.unsupported_controller".enabled = false`

Everything else of ADR 0031 stands unchanged: the condition is switched off with `enabled = false` under the identifier in `[checks."<id>"]`, and the configuration accepts the dotted key as the same table.

## Consequences

- A test takes the line out of the notice, writes it into a configuration file and loads it; the condition is off afterwards. The test fails against the earlier sentence, because the line is not TOML.
- The notice stays one sentence of one line, and it now names a setting that the reader can paste without editing it.
- `config.reference.toml` keeps the table form, because it lists every condition under its own header. The dotted key and the table set the same value, and a test keeps both forms valid.
- The identifier of the condition remains a configuration key and a stable interface (NFR-21); only the sentence that names it changes.

## Revisit when

- The notice has to carry more than one setting, or a setting that a dotted key cannot express; the message format then needs a place for a configuration snippet of its own.
