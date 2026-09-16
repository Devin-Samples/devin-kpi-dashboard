"""README KPI-definitions section stays in sync with the registry."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from gen_definitions_md import render


def test_readme_definitions_section():
    readme = (ROOT / "README.md").read_text()
    m = re.search(
        r"<!-- KPI_DEFINITIONS_START -->\n(.*)\n<!-- KPI_DEFINITIONS_END -->",
        readme,
        re.DOTALL,
    )
    assert m, "README missing KPI_DEFINITIONS markers"
    # strip the generator's own top heading (the README has a section title)
    expected = render().split("# KPI definitions", 1)[1].strip()
    assert m.group(1).strip() == expected
