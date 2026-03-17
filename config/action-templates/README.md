# Action Templates

Store reusable action-template definitions here.

Templates are static capability definitions. They should not contain thread-specific payloads.

Typical templates:

- `build-daily-digest`
- `summarize-thread`
- `remind-owner`
- `draft-reply`

Thread-specific action instances belong in runtime data, not in this directory.
