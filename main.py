"""Backward-compatible launcher for the installed ``thessla-green`` CLI.

The old hard-coded COM3 experiment has moved into the configurable protocol
and discovery layers. Use ``python -m thessla_green discover`` or the installed
``thessla-green discover`` command.
"""

from thessla_green.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
