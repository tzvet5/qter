from unittest.mock import MagicMock

import pytest
from qtgql.codegen.py.runtime.environment import ENV_MAP, QtGqlEnvironment
from qtgql.codegen.py.runtime.queryhandler import BaseQueryHandler
from qtgql.gqltransport.client import GqlWsTransportClient


@pytest.fixture()
def pseudo_environment():
    ENV_MAP["DEFAULT"] = QtGqlEnvironment(GqlWsTransportClient(url=""))
    yield ENV_MAP["DEFAULT"]
    ENV_MAP.pop("DEFAULT")


def test_is_singleton(pseudo_environment):
    class Foo(BaseQueryHandler):
        ...

    assert Foo() is Foo()


def test_fetch_when_graphql_is_set(pseudo_environment):
    class Foo(BaseQueryHandler):
        ...

    inst = Foo()
    inst.fetch = MagicMock()
    Foo().set_graphql("bar")
    assert inst.fetch.called
