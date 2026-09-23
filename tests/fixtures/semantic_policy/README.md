# Synthetic semantic-policy fixtures

These three Packs exercise one engine with different opaque business category IDs. They are **synthetic contract fixtures only**:

| Fixture | Opaque category emitted | What it proves |
|---|---|---|
| `delivery.yaml` | `delivery.review` | A delivery-flavoured vocabulary can be supplied by configuration. |
| `commercial.yaml` | `commercial.review` | The same input shape can project a different business vocabulary. |
| `operations.yaml` | `operations.review` | A third domain needs no client or engine enum change. |

They are not real department policies, not an organization model, and not an ACL or source grant. Their `department` tags are display/business semantics only and cannot authorize reads, execution, or feedback. The historical G1–G6 and C1–C10 gold cases are intentionally left unchanged; these fixtures neither replace nor enlarge that gold set. Any real Pack, gold label, or ROI claim still requires confirmation by the authorized business owner in the private evaluation baseline.
