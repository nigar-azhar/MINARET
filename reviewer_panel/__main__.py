import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the repo root, for `minaret`

from reviewer_panel.server import main  # noqa: E402

main()
