import typing

import pytest
from qtgql.codegen.introspection import introspection_query
from qtgql.codegen.py.compiler.builtin_scalars import BuiltinScalar, BuiltinScalars
from qtgql.codegen.py.runtime.bases import QGraphQListModel, _BaseQGraphQLObject
from qtgql.codegen.py.runtime.custom_scalars import (
    BaseCustomScalar,
    DateTimeScalar,
)
from qtgql.typingref import TypeHinter

from tests.mini_gql_server import schema
from tests.test_codegen.test_py.testcases import (
    DateTimeTestCase,
    EnumTestCase,
    InterfaceTestCase,
    NestedObjectTestCase,
    ObjectsThatReferenceEachOtherTestCase,
    ObjectWithListOfObjectTestCase,
    OptionalNestedObjectTestCase,
    QGQLObjectTestCase,
    ScalarsTestCase,
    UnionTestCase,
    all_test_cases,
    custom_scalar_testcases,
)


@pytest.fixture
def introspected():
    return schema.execute_sync(introspection_query)


@pytest.mark.parametrize("testcase", all_test_cases, ids=lambda x: x.test_name)
def test_init_no_arguments(testcase: QGQLObjectTestCase):
    testcase.compile()
    assert isinstance(testcase.gql_type(None), _BaseQGraphQLObject)


class TestAnnotations:
    @pytest.mark.parametrize("scalar", BuiltinScalars, ids=lambda v: v.graphql_name)
    def test_scalars(self, scalar: BuiltinScalar):
        ScalarsTestCase.compile()
        field = ScalarsTestCase.get_field_by_type(scalar)
        assert field, f"field not found for {scalar.graphql_name}: {scalar}"
        klass = ScalarsTestCase.gql_type
        assert (
            scalar.tp
            == TypeHinter.from_string(
                getattr(klass, field.setter_name).__annotations__["v"], ns=field.type_map
            ).as_annotation()
        )
        assert (
            scalar.tp
            == TypeHinter.from_string(
                getattr(klass, field.name).fget.__annotations__["return"], ns=field.type_map
            ).as_annotation()
        )

    @pytest.mark.parametrize("testcase, scalar, fname", custom_scalar_testcases)
    def test_custom_scalars(
        self, testcase: QGQLObjectTestCase, scalar: typing.Type[BaseCustomScalar], fname
    ):
        testcase.compile()
        field = testcase.get_field_by_type(scalar)
        assert field, f"field {field} not found"
        klass = testcase.gql_type
        assert field.annotation == f"SCALARS.{scalar.__name__}"
        assert getattr(klass, field.setter_name).__annotations__["v"] == field.annotation
        assert getattr(klass, field.name).fget.__annotations__["return"] == field.fget_annotation
        assert (
            TypeHinter.from_string(
                field.fget_annotation, ns={"Optional": typing.Optional}
            ).as_annotation()
            == scalar.to_qt.__annotations__["return"]
        )

    def test_list_of(self):
        testcase = ObjectWithListOfObjectTestCase
        testcase.compile()
        field = testcase.get_field_by_name("persons")
        assert field.annotation == f"{QGraphQListModel.__name__}[{field.type.is_model.name}]"
        assert field.fget_annotation == f"{QGraphQListModel.__name__}[{field.type.is_model.name}]"

    def test_custom_scalar_property_type_is_to_qt_return_annotation(self):
        testcase = DateTimeTestCase
        testcase.compile()
        to_qt = TypeHinter.from_annotations(DateTimeScalar.to_qt.__annotations__["return"])
        assert testcase.get_field_by_name("birth").property_type == to_qt.stringify()

    def test_enums(self):
        testcase = EnumTestCase.compile()
        enum_field = testcase.get_field_by_name("status")
        assert enum_field.property_type == "int"
        assert enum_field.fget_annotation == "int"
        assert enum_field.annotation == "Status"


class TestPropertyGetter:
    def default_test(self, testcase: QGQLObjectTestCase, field_name: str):
        testcase.compile()
        klass = testcase.gql_type
        initialize_dict = testcase.initialize_dict
        inst = klass.from_dict(None, initialize_dict)
        field = testcase.get_field_by_name(field_name)
        assert inst.property(field.name)

    def test_scalars(self, qtbot):
        testcase = ScalarsTestCase
        testcase.compile()
        klass = testcase.gql_type
        initialize_dict = testcase.initialize_dict
        inst = klass.from_dict(None, initialize_dict)
        for field in testcase.tested_type.fields:
            v = inst.property(field.name)
            assert v == initialize_dict[field.name]

    def test_datetime_scalar(self, qtbot):
        self.default_test(DateTimeTestCase, "birth")

    def test_nested_object(self, qtbot):
        self.default_test(NestedObjectTestCase, "person")

    def test_list_of(self, qtbot):
        self.default_test(ObjectWithListOfObjectTestCase, "persons")

    def test_union(self, qtbot):
        self.default_test(UnionTestCase, "whoAmI")

    def test_enum(self):
        testcase = EnumTestCase.compile()
        inst = testcase.gql_type.from_dict(None, data=testcase.initialize_dict)
        f = testcase.get_field_by_name("status")
        assert inst.property(f.name) == testcase.module.Status.Connected.value


class TestDeserializers:
    @pytest.mark.parametrize("testcase", all_test_cases, ids=lambda x: x.test_name)
    def test_blank_dict(self, testcase: QGQLObjectTestCase):
        testcase.compile()
        assert isinstance(testcase.gql_type.from_dict(None, {}), testcase.gql_type)

    def test_scalars(self, qtbot):
        testcase = ScalarsTestCase
        testcase.compile()
        klass = testcase.gql_type
        initialize_dict = testcase.initialize_dict
        inst = klass.from_dict(None, initialize_dict)
        for field in testcase.tested_type.fields:
            v = getattr(inst, field.private_name)
            assert v == initialize_dict[field.name]

    def test_nested_object_from_dict(self, qtbot):
        testcase = NestedObjectTestCase
        testcase.compile()
        klass = testcase.gql_type
        inst = klass.from_dict(None, testcase.initialize_dict)
        assert inst.person.name == "Patrick"
        assert inst.person.age == 100

    def test_nested_optional_object_is_null(self):
        testcase = OptionalNestedObjectTestCase.compile()
        inst = testcase.gql_type.from_dict(None, testcase.initialize_dict)
        assert inst.person is None

    def test_object_with_list_of_object(self):
        testcase = ObjectWithListOfObjectTestCase.compile()
        inst = testcase.gql_type.from_dict(None, testcase.initialize_dict)
        assert isinstance(inst.persons, QGraphQListModel)
        assert inst.persons._data[0].name

    def test_object_with_interface(self):
        testcase = InterfaceTestCase.compile()
        inst = testcase.gql_type.from_dict(None, testcase.initialize_dict)
        assert inst.name

    @pytest.mark.parametrize("testcase, scalar, fname", custom_scalar_testcases)
    def test_custom_scalars(
        self, testcase: QGQLObjectTestCase, scalar: BaseCustomScalar, fname: str
    ):
        testcase.compile()
        klass = testcase.gql_type
        initialize_dict = testcase.initialize_dict
        initialize_dict["country"] = "isr"
        inst = klass.from_dict(None, initialize_dict)
        field = testcase.get_field_by_name(fname)
        assert inst.property(field.name) == scalar.from_graphql(initialize_dict[field.name]).to_qt()

    def test_enum(self):
        testcase = EnumTestCase.compile()
        inst = testcase.gql_type.from_dict(None, data=testcase.initialize_dict)
        f = testcase.get_field_by_name("status")
        assert getattr(inst, f.private_name) == testcase.module.Status.Connected


class TestDefaultConstructor:
    @pytest.mark.parametrize("scalar", BuiltinScalars, ids=lambda v: v.graphql_name)
    def test_builtin_scalars(self, scalar: BuiltinScalar):
        testcase = ScalarsTestCase
        testcase.compile()
        klass = testcase.gql_type
        inst = klass()
        f = testcase.get_field_by_type(scalar)
        assert getattr(inst, f.private_name) == scalar.default_value

    def test_nested_object_from_dict(self, qtbot):
        # types that refer each-other can cause recursion error
        # This is why we set object types to null.
        testcase = NestedObjectTestCase.compile()
        klass = testcase.gql_type
        inst = klass()
        assert inst.person is None

    def test_object_with_list_of_object(self):
        testcase = ObjectWithListOfObjectTestCase.compile()
        inst = testcase.gql_type()
        assert isinstance(inst.persons, QGraphQListModel)
        # by default there is no need for initializing delegates.
        assert len(inst.persons._data) == 0

    @pytest.mark.parametrize("testcase, scalar, fname", custom_scalar_testcases)
    def test_custom_scalars(
        self, testcase: QGQLObjectTestCase, scalar: BaseCustomScalar, fname: str
    ):
        testcase.compile()
        inst = testcase.gql_type()
        field = testcase.get_field_by_name(fname)
        assert getattr(inst, field.private_name).to_qt() == scalar().to_qt()

    def test_enum(self):
        testcase = EnumTestCase.compile()
        inst = testcase.gql_type()
        f = testcase.get_field_by_name("status")
        assert (
            getattr(inst, f.private_name)
            == testcase.module.Status(1)
            == testcase.module.Status.Connected
        )

    def test_union(self):
        testcase = UnionTestCase.compile()
        testcase.gql_type()

    def test_wont_recursive(self):
        testcase = ObjectsThatReferenceEachOtherTestCase.compile()
        testcase.gql_type()
