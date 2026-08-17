#!/usr/bin/env python3
"""CC_Launcher — entry point.

Deliberately thin. Everything lives in the cc_launcher package next to this
file, which Python finds because the script's own directory heads sys.path.
"""
from cc_launcher.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
