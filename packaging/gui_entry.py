import sys

if len(sys.argv) > 1 and not sys.argv[1].startswith("-psn"):
    from autodrums.cli import main
else:
    from autodrums.gui.app import main

sys.exit(main())
