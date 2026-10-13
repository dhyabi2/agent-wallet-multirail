"""A README command that imports the package must come after the install step.

`src/` layout: the package is importable only once it is installed (or with
`src` on `PYTHONPATH`, which is what `pyproject.toml`'s `pythonpath = [".",
"src"]` does for pytest, and what `sys.path.insert(0, "src")` does at the top of
the test modules). Three of the six shipped examples are self-contained and run
straight from a clone; the other three import `agent_wallet_multirail`, so from
a fresh clone with no install they end at

    ModuleNotFoundError: No module named 'agent_wallet_multirail'

The README's "Run it" section gets this right -- `pip install -e .` and then the
examples, in one block. But the swap-hop section above it opened with a bare

    python3 examples/pay_nano_quote_from_usdc.py

and that is the *first* runnable command in the document, 40-odd lines before
any install step. A reader working top-down -- which is what an agent asked to
"follow the README" does -- ran it and got the traceback above as its first
contact with this repository.

This law fixes the ordering rather than the wording: for every
`python3 examples/<name>.py` the README shows, if that example imports the
package then a `pip install` must appear earlier in the file. It reads the
examples' own imports, so an example that is rewritten to be self-contained
(or a new one that is not) is covered without editing this file.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, "src")

ROOT = Path(__file__).resolve().parents[1]
README_TEXT = (ROOT / "README.md").read_text()
PACKAGE = "agent_wallet_multirail"

_EXAMPLE_COMMAND = re.compile(r"^\s*python3? +(examples/([A-Za-z0-9_]+)\.py)", re.M)
_PIP_INSTALL = re.compile(r"^\s*pip install ", re.M)


def _imports_the_package(example: Path) -> bool:
    """True when the example needs the package on the path to start at all."""
    return bool(
        re.search(rf"^\s*(?:from|import) +{re.escape(PACKAGE)}\b", example.read_text(), re.M)
    )


def _commands():
    """(offset, relative path) for every example the README tells the reader to run."""
    return [(m.start(), m.group(1)) for m in _EXAMPLE_COMMAND.finditer(README_TEXT)]


def _first_install_offset():
    match = _PIP_INSTALL.search(README_TEXT)
    return match.start() if match else None


def test_the_readme_runs_examples_so_this_law_can_see_them():
    """Guard the parser: a README that stopped matching would disarm the law below."""
    commands = _commands()
    assert commands, (
        "no `python3 examples/...` command was parsed out of the README; the command "
        "shape changed, so fix this parser rather than deleting the law below."
    )
    for _, relative in commands:
        assert (ROOT / relative).is_file(), (
            f"the README tells the reader to run {relative}, which does not exist"
        )


def test_every_example_the_readme_runs_imports_cleanly_or_follows_an_install():
    install_at = _first_install_offset()
    for offset, relative in _commands():
        if not _imports_the_package(ROOT / relative):
            continue  # self-contained: it runs straight from a clone
        line = README_TEXT.count("\n", 0, offset) + 1
        assert install_at is not None and install_at < offset, (
            f"README line {line} runs `{relative}`, which imports {PACKAGE}, but no "
            f"`pip install` appears before it. From a fresh clone that command ends at "
            f"ModuleNotFoundError: No module named '{PACKAGE}' -- and this is the first "
            f"runnable command a reader working top-down reaches. Name the install in "
            f"that block, as the 'Run it' section does."
        )
