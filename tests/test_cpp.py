from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from conanfile import Qt6Installer

from tests.conftest import IS_WINDOWS, IS_GITHUB_ACTION
from tests.doctest_finder import Catch2TestCase, collect_tests

if TYPE_CHECKING:
    from tests.conftest import MiniServer


if IS_GITHUB_ACTION:
    qt6_installer = Qt6Installer("windows" if IS_WINDOWS else "linux", "6.5.2")
    qt6_installer.set_env_vars()


@pytest.mark.parametrize("doctest_testcase", collect_tests(), ids=lambda v: v.test_name, )
def test_generated_tests(doctest_testcase: Catch2TestCase, schemas_server: MiniServer):
    os.environ.setdefault("SCHEMAS_SERVER_ADDR", schemas_server.address)
    doctest_testcase.run()
