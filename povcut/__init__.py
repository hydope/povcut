"""POVCut — turn Ray-Ban Meta footage into viral shorts with one command."""

import os as _os
from pathlib import Path as _Path

# Publishing goes through the shared creator-publish package; keep
# POVCut's tokens in its own home dir.
_os.environ.setdefault(
    "CREATOR_PUBLISH_HOME", str(_Path.home() / ".povcut"))

__version__ = "0.1.0"
__all__ = ["__version__"]
