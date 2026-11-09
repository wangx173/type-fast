"""Entry point for the packaged Type Fast app."""

import os
import sys

SMOKE_TEST = sys.argv[1:] == ["--smoke-test"]
if SMOKE_TEST:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from type_fast.app import main

if __name__ == "__main__":
    if SMOKE_TEST:
        sys.exit(main(smoke_test=True))
    main()
