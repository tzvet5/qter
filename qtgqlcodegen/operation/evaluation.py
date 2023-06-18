from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

import graphql
from frozendict import frozendict
from graphql import OperationDefinitionNode, OperationType, language as gql_lang
from graphql.language import visitor

from qtgqlcodegen.core.graphql_ref import (
    has_id_selection,
    has_typename_selection,
    inject_id_selection,
    inject_typename_selection,
    is_field_node,
    is_inline_fragment,
    is_named_type_node,
    is_nonnull_node,
    is_operation_def_node,
)
from qtgqlcodegen.operation.definitions import (
    OperationTypeInfo,
    QtGqlOperationDefinition,
    QtGqlQueriedField,
)
from qtgqlcodegen.schema.definitions import (
    QtGqlVariableDefinition,
    SchemaTypeInfo,
)
from qtgqlcodegen.schema.evaluation import evaluate_graphql_type
from qtgqlcodegen.types import QtGqlQueriedObjectType
from qtgqlcodegen.utils import UNSET, require

if TYPE_CHECKING:
    from qtgqlcodegen.core.cppref import CppAccessor
    from qtgqlcodegen.types import QtGqlObjectType, QtGqlTypeABC


def is_type_name_selection(field_node: gql_lang.FieldNode):
    # typename is not a 'real' selection and is handled with special care.
    if field_node.name.value == "__typename":
        return True
    return False


def _evaluate_field_arguments(type_info: OperationTypeInfo):
    ...


def _get_cpp_accessor_from_variable_use() -> CppAccessor:
    ...


def _evaluate_field(
    type_info: OperationTypeInfo,
    field_type: QtGqlObjectType,
    field_node: gql_lang.FieldNode,
    parent_interface_field: QtGqlQueriedField | None = UNSET,
    is_root: bool = False,
) -> QtGqlQueriedField:
    """Main purpose here is to find inner selections of fields, this could be
    an object type, interface, union or a list.

    Any other fields should not have inner selections.
    """
    concrete_field = field_type.fields_dict[field_node.name.value]
    if field_node.arguments:
        for arg in field_node.arguments:
            index = concrete_field.index_for_argument(arg.name.value)
        _get_cpp_accessor_from_variable_use()
    assert parent_interface_field is not UNSET

    tp = concrete_field.type
    if tp.is_model:  # GraphQL's lists are basically the object beneath them in terms of selections.
        tp = tp.is_model

    tp_is_union = tp.is_union

    selections_set = field_node.selection_set
    if not selections_set:  # this is a scalar / enum field.
        return QtGqlQueriedField(concrete=concrete_field, type_info=type_info, is_root=is_root)
    # inject id selection for types that supports it. unions are handled below.
    if concrete_field.can_select_id and not has_id_selection(selections_set):
        inject_id_selection(selections_set)

    selections: dict[str, QtGqlQueriedField] = {}
    choices: defaultdict[str, dict[str, QtGqlQueriedField]] = defaultdict(dict)
    narrowed_type: QtGqlQueriedObjectType | None = None

    # inject parent interface selections.
    if (tp.is_object_type or tp.is_interface) and parent_interface_field:
        selections.update({f.name: f for f in parent_interface_field.selections.values()})

    if tp_is_union:
        for selection in selections_set.selections:
            fragment = is_inline_fragment(selection)
            assert fragment

            type_name = fragment.type_condition.name.value
            concrete = type_info.schema_type_info.get_object_type(type_name)
            assert concrete
            if not has_typename_selection(fragment.selection_set):
                inject_typename_selection(fragment.selection_set)
            if not has_id_selection(fragment.selection_set) and concrete.implements_node:
                inject_id_selection(fragment.selection_set)

            for selection_node in fragment.selection_set.selections:
                inner_field_node = is_field_node(selection_node)
                assert inner_field_node

                if not is_type_name_selection(inner_field_node):
                    __f = _evaluate_field(
                        type_info,
                        concrete,
                        inner_field_node,
                        parent_interface_field,
                    )
                    choices[type_name][concrete_field.name] = __f

    elif interface_def := tp.is_interface:
        # first get all linear selections.
        for selection in selections_set.selections:
            if not is_inline_fragment(selection):
                inner_field_node = is_field_node(selection)
                assert inner_field_node
                if not is_type_name_selection(inner_field_node):
                    __f = _evaluate_field(
                        type_info,
                        interface_def,
                        inner_field_node,
                        parent_interface_field,
                    )
                    selections[__f.name] = __f

        for selection in selections_set.selections:
            if inline_frag := is_inline_fragment(selection):
                type_name = inline_frag.type_condition.name.value
                # no need to validate inner types are implementation, graphql-core does this.
                concrete = type_info.schema_type_info.get_object_type(
                    type_name,
                ) or type_info.schema_type_info.get_interface(type_name)
                assert concrete
                for inner_selection in inline_frag.selection_set.selections:
                    inner_field_node = is_field_node(inner_selection)
                    assert inner_field_node
                    if not is_type_name_selection(inner_field_node):
                        __f = _evaluate_field(
                            type_info,
                            concrete,
                            inner_field_node,
                            parent_interface_field,
                        )
                        choices[type_name][concrete_field.name] = __f

    else:  # object types.
        concrete = tp.is_object_type
        assert concrete
        for selection in selections_set.selections:
            inner_field_node = is_field_node(selection)
            assert inner_field_node
            if not is_type_name_selection(inner_field_node):
                __f = _evaluate_field(
                    type_info,
                    concrete,
                    inner_field_node,
                    parent_interface_field,
                )
                selections[__f.name] = __f
        queried_obj = QtGqlQueriedObjectType(
            concrete=concrete,
            fields_dict=selections,
        )
        type_info.narrowed_types_map[queried_obj.name] = queried_obj
        narrowed_type = queried_obj

    def sorted_distinct_fields(
        fields: dict[str, QtGqlQueriedField],
    ) -> dict[str, QtGqlQueriedField]:
        return dict(sorted(fields.items()))

    return QtGqlQueriedField(
        concrete=concrete_field,
        selections=sorted_distinct_fields(selections),
        choices=frozendict({k: sorted_distinct_fields(v) for k, v in choices.items()}),
        type_info=type_info,
        narrowed_type=narrowed_type,
        is_root=is_root,
    )


def _evaluate_variable_node_type(
    type_info: SchemaTypeInfo,
    node: graphql.TypeNode,
) -> QtGqlTypeABC:
    if nonnull := is_nonnull_node(node):
        return evaluate_graphql_type(
            type_info,
            graphql.type.GraphQLNonNull(
                type_info.schema_definition.get_type(nonnull.type.name.value),  # type: ignore
            ),
        )

    if named_type := is_named_type_node(node):
        gql_concrete = type_info.schema_definition.get_type(named_type.name.value)
        assert gql_concrete
        return evaluate_graphql_type(type_info, gql_concrete)
    raise NotImplementedError(node, "Type is not supported as a variable ATM")


def _evaluate_variable(
    type_info: SchemaTypeInfo,
    var: gql_lang.VariableDefinitionNode,
) -> QtGqlVariableDefinition:
    return QtGqlVariableDefinition(
        name=var.variable.name.value,
        type=_evaluate_variable_node_type(type_info, var.type),
    )


def _evaluate_operation(
    operation: OperationDefinitionNode,
    schema_type_info: SchemaTypeInfo,
) -> QtGqlOperationDefinition:
    type_info = OperationTypeInfo(schema_type_info)

    # input variables
    if variables_def := operation.variable_definitions:
        for var in variables_def:
            type_info.variables.append(_evaluate_variable(type_info.schema_type_info, var))

    root_field_def = require(is_field_node(operation.selection_set.selections[0]))
    root_type = type_info.schema_type_info.operation_types[operation.operation.value]
    assert root_type, f"Make sure you have {operation.operation.name} type defined in your schema"
    root_field = _evaluate_field(
        type_info,
        root_type,
        root_field_def,
        parent_interface_field=None,
        is_root=True,
    )
    return QtGqlOperationDefinition(
        root_field=root_field,
        operation_def=operation,
        variables=type_info.variables,
        narrowed_types=tuple(type_info.narrowed_types_map.values()),
    )


class _OperationsVisitor(visitor.Visitor):
    def __init__(self, type_info: SchemaTypeInfo):
        super().__init__()
        self.schema_type_info = type_info
        self.operations: dict[str, QtGqlOperationDefinition] = {}

    def enter_operation_definition(self, node, key, parent, path, ancestors) -> None:
        if operation := is_operation_def_node(node):
            if operation.operation in (
                OperationType.QUERY,
                OperationType.MUTATION,
                OperationType.SUBSCRIPTION,
            ):
                assert operation.name, "QtGql enforces operations to have names."
                self.operations[operation.name.value] = _evaluate_operation(
                    operation,
                    self.schema_type_info,
                )


def evaluate_operations(
    operations_document: graphql.DocumentNode,
    type_info: SchemaTypeInfo,
) -> dict[str, QtGqlOperationDefinition]:
    operation_visitor = _OperationsVisitor(type_info)
    graphql.visit(operations_document, operation_visitor)
    assert operation_visitor.operations
    return operation_visitor.operations
