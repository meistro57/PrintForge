"""Allow ``python -m printforge``."""

import sys

from printforge.cli import main

if __name__ == "__main__":
    sys.exit(main())
