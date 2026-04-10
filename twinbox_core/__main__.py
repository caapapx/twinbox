"""Allow `python3 -m twinbox_core` as alias for `python3 -m twinbox_core.cli`."""
from twinbox_core.cli import main

raise SystemExit(main())
