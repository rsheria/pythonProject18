"""Test configuration helpers."""

import pathlib
import sys
import types

# Ensure the project root is importable regardless of the individual test
# being executed.  Some tests rely on absolute imports like ``integrations``
# which require the repository root on ``sys.path``.
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Provide a minimal stub for the optional ``myjdapi`` dependency used by the
# JDownloader integration.  The real package is not needed for the tests and
# isn't available in the execution environment.
if "myjdapi" not in sys.modules:
    sys.modules["myjdapi"] = types.SimpleNamespace(Myjdapi=object)

