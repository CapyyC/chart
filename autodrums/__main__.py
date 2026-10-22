import sys

if len(sys.argv) > 1:
    from autodrums.cli import main
else:
    from autodrums.gui.app import main

sys.exit(main())
