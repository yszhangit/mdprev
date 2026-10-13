import sys

if sys.platform == "darwin":
    from .macos.app import main
else:
    from .gtk.app import main

raise SystemExit(main())
