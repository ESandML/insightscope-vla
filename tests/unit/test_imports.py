"""Smoke tests: the package installs, imports, and reports a sane version.

This exists so CI has something real to run from the very first commit.
If these fail, nothing else in the project can be trusted.
"""

import re

import insightscope


def test_package_imports() -> None:
    assert insightscope.__version__


def test_version_looks_like_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", insightscope.__version__)
