from __future__ import annotations

from typing import TYPE_CHECKING

import attrs
import graphql
from attr import define
from graphql import OperationDefinitionNode, OperationType, language as gql_lang
from graphql.language import visitor

from qtgqlcodegen.core.graphql_ref import (
    has_id_selection,
    has_typename_selection,
    inject_id_selection,
    inject_typename_selection,
    is_field_node,
    is_fragment_definition_node,
    is_fragment_spread_node,
    is_inline_fragment,
    is_named_type_node,
    is_nonnull_node,
    is_operation_def_node,
)
from qtgqlcodegen.operation.definitions import (
    OperationTypeInfo,
    QtGqlFragmentDefinition,
    QtGqlOperationDefinition,
    QtGqlQueriedField,
    QtGqlVariableUse,
)
from qtgqlcodegen.schema.definitions import (
    QtGqlFieldDefinition,
    QtGqlVariableDefinition,
    SchemaTypeInfo,
)
from qtgqlcodegen.schema.evaluation import evaluate_graphql_type
from qtgqlcodegen.types import (
    QtGqlInterface,
    QtGqlList,
    QtGqlOptional,
    QtGqlQueriedInterface,
    QtGqlQueriedObjectType,
    QtGqlQueriedUnion,
    QtGqlUnion,
)
from qtgqlcodegen.utils import require

if TYPE_CHECKING:
    from qtgqlcodegen.types import QtGqlObjectType, QtGqlTypeABC


def is_type_name_selection(field_node: gql_lang.FieldNode):
    # typename is not a 'real' selection and is handled with special care.
    if field_node.name.value == "__typename":
        return True
    return False


def _evaluate_variable_uses(
    type_info: OperationTypeInfo,
    field: QtGqlFieldDefinition,
    arguments: tuple[gql_lang.ArgumentNode, ...],
) -> list[QtGqlVariableUse]:
    ret: list[QtGqlVariableUse] = []
    for arg in arguments:
        index = field.index_for_argument(arg.name.value)
        var_name = arg.value.name.value  # type: ignore[attr-defined]
        for variable in type_info.variables:
            if var_name == variable.name:
                ret.append(
                    QtGqlVariableUse(argument=(index, field.arguments[index]), variable=variable),
                )
    assert len(ret) == len(arguments), "could not find all variable uses"
    return sorted(ret, key=lambda v: v.argument[0])


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


def _evaluate_selection_set_type(
    type_info: OperationTypeInfo,
    concrete_type: QtGqlTypeABC,
    selection_set_node: gql_lang.SelectionSetNode | None,
    path: str,
) -> QtGqlTypeABC:
    ret: QtGqlTypeABC | None = None
    if not selection_set_node:
        # these types have no selections
        assert (
            concrete_type.is_builtin_scalar
            or concrete_type.is_custom_scalar
            or concrete_type.is_enum
        )
        ret = concrete_type  # currently there is no need for a "proxied" type.

    elif obj_type := concrete_type.is_object_type:
        ret = _evaluate_object_type(
            type_info=type_info,
            concrete=obj_type,
            selection_set=selection_set_node,
            path=path,
        )
    elif lst := concrete_type.is_model:
        ret = _evaluate_list(
            type_info=type_info,
            concrete=lst,
            selection_set=selection_set_node,
            path=path,
        )
    elif interface := concrete_type.is_interface:
        ret = _evaluate_interface(
            type_info=type_info,
            concrete=interface,
            selection_set=selection_set_node,
            path=path,
        )
    elif is_union := concrete_type.is_union:
        ret = _evaluate_union(
            type_info=type_info,
            concrete=is_union,
            selection_set=selection_set_node,
            path=path,
        )
    if not ret:  # pragma: no cover
        raise NotImplementedError(f"type {concrete_type} not supported yet")

    if concrete_type.is_optional:
        return QtGqlOptional(of_type=ret)
    return ret


def _evaluate_field(
    type_info: OperationTypeInfo,
    concrete_field: QtGqlFieldDefinition,
    field_node: gql_lang.FieldNode,
    path: str,
    origin: QtGqlObjectType,
) -> QtGqlQueriedField:
    path += concrete_field.name
    return QtGqlQueriedField(
        type=_evaluate_selection_set_type(
            type_info,
            concrete_field.type,
            field_node.selection_set,
            path,
        ),
        concrete=concrete_field,
        variable_uses=_evaluate_variable_uses(type_info, concrete_field, field_node.arguments),
        origin=origin,
        type_info=type_info,
    )


def _evaluate_list(
    type_info: OperationTypeInfo,
    concrete: QtGqlList,
    selection_set: gql_lang.SelectionSetNode,
    path: str,
) -> QtGqlList:
    return QtGqlList(
        of_type=_evaluate_selection_set_type(
            type_info,
            concrete_type=concrete.of_type,
            selection_set_node=selection_set,
            path=path,
        ),
    )


def _evaluate_union(
    type_info: OperationTypeInfo,
    concrete: QtGqlUnion,
    selection_set: gql_lang.SelectionSetNode,
    path: str,
) -> QtGqlQueriedUnion:
    choices: dict[str, QtGqlQueriedObjectType] = {}
    if not has_typename_selection(selection_set):
        inject_typename_selection(selection_set)
    for selection in selection_set.selections:
        if is_field_node(selection):
            continue  # __typename selection
        fragment = is_inline_fragment(selection)
        assert fragment
        type_name = fragment.type_condition.name.value
        # unions support only object types http://spec.graphql.org/October2021/#sec-Unions
        resolved_type = require(concrete.get_by_name(type_name))
        choices[type_name] = _evaluate_object_type(
            type_info=type_info,
            concrete=resolved_type,
            selection_set=fragment.selection_set,
            path=path,
        )

    return QtGqlQueriedUnion(
        concrete=concrete,
        choices=tuple(choices.values()),
    )


@define
class _FieldsAndFragments:
    fields: list[gql_lang.FieldNode] = attrs.Factory(list)
    used_fragments: list[QtGqlFragmentDefinition] = attrs.Factory(list)


def _unwrap_interface_fragments(
    type_info: OperationTypeInfo,
    parent_concrete: QtGqlObjectType | QtGqlInterface,
    selection_set: gql_lang.SelectionSetNode,
    initial: dict[str, _FieldsAndFragments],
    id_was_selected: bool = False,
) -> dict[str, _FieldsAndFragments]:
    """Fragments can be nested, i.e node{ id.

    ...on SomeFrag{
            field1
            ...on Obj{
                name
            }
        }
    }
    :return: unwrap everything and return the selections mapped to object types.
    """

    concrete_selections = _FieldsAndFragments()
    if (
        parent_concrete.implements_node
        and not has_id_selection(selection_set)
        and not id_was_selected
    ):
        id_was_selected = True
        inject_id_selection(selection_set)
    for node in selection_set.selections:
        if inline_frag := is_inline_fragment(node):
            type_name = inline_frag.type_condition.name.value
            # no need to validate inner types are implementation, graphql-core does this.
            concrete_choice = type_info.schema_type_info.get_object_or_interface(type_name)
            _unwrap_interface_fragments(
                type_info,
                concrete_choice,
                inline_frag.selection_set,
                initial,
                id_was_selected,
            )
        elif frag_spread := is_fragment_spread_node(node):
            concrete_selections.used_fragments.append(_evaluate_fragment(type_info, frag_spread))
        else:
            field_node = is_field_node(node)
            assert field_node
            if field_node.name.value != "__typename":
                concrete_selections.fields.append(field_node)

    initial[parent_concrete.name] = concrete_selections
    return initial


def _evaluate_interface(
    type_info: OperationTypeInfo,
    concrete: QtGqlInterface,
    selection_set: gql_lang.SelectionSetNode,
    path: str,  # current path in the query tree.
) -> QtGqlQueriedInterface:
    choices: list[QtGqlQueriedObjectType] = []

    raw_fields_map = _unwrap_interface_fragments(
        type_info,
        concrete,
        selection_set,
        {},
    )
    # dispatch fragmented fields where they are needed.
    for resolve_able in concrete.implementations.values():
        if concrete_choice := resolve_able.is_object_type:
            selections_for_obj = _FieldsAndFragments()
            # collect fields from bases.
            for base in concrete_choice.interfaces_raw:
                if selections_for_base := raw_fields_map.get(base.name, None):
                    selections_for_obj.fields.extend(selections_for_base.fields)
                    selections_for_obj.used_fragments.extend(selections_for_base.used_fragments)

            # append fields of the choice itself
            if choice_fields := raw_fields_map.get(concrete_choice.name, None):
                selections_for_obj.fields.extend(choice_fields.fields)
                selections_for_obj.used_fragments.extend(choice_fields.used_fragments)

            ss = gql_lang.SelectionSetNode(selections=tuple(selections_for_obj.fields))
            # This could probably be more optimized though, currently
            # this would suffice to reduce complexity.
            obj = _evaluate_object_type(
                type_info=type_info,
                concrete=concrete_choice,
                selection_set=ss,
                path=path,
            )
            for frag in selections_for_obj.used_fragments:
                obj.fields_dict.update(frag.of.fields_dict)
            choices.append(obj)

    # inject __type_name selection, we'll use this to deserialize correctly.
    if not has_typename_selection(selection_set):
        inject_typename_selection(selection_set)

    name = f"{concrete.name}__{path}"
    fields_for_interface = {
        field.name.value: _evaluate_field(
            type_info=type_info,
            concrete_field=concrete.fields_dict[field.name.value],
            path=path,
            field_node=field,
            origin=concrete,
        )
        for field in raw_fields_map[concrete.name].fields
    }
    for used_frag in raw_fields_map[concrete.name].used_fragments:
        fields_for_interface.update(
            used_frag.of.fields_dict,
        )
    ret = QtGqlQueriedInterface(
        name=name,
        concrete=concrete,
        choices=choices,
        fields_dict=fields_for_interface,
    )
    for choice in choices:
        choice.base_interface = ret
    type_info.narrowed_interfaces_map[name] = ret
    return ret


def _evaluate_object_type(
    type_info: OperationTypeInfo,
    concrete: QtGqlObjectType,
    selection_set: gql_lang.SelectionSetNode,
    path: str,  # current path in the query tree.
) -> QtGqlQueriedObjectType:
    # inject id selection for node implementors, it is required for caching purposes.
    if concrete.implements_node and not has_id_selection(selection_set):
        inject_id_selection(selection_set)

    fields: dict[str, QtGqlQueriedField] = {}
    for selection in selection_set.selections:
        if f_node := is_field_node(selection):
            if is_type_name_selection(f_node):
                continue  # __typename selection is handled with special care.
            concrete_field = concrete.fields_dict[f_node.name.value]
            fields[concrete_field.name] = _evaluate_field(
                type_info=type_info,
                concrete_field=concrete_field,
                field_node=f_node,
                path=path,
                origin=concrete,
            )
        elif frag_spread := is_fragment_spread_node(selection):
            resolved_frag = _evaluate_fragment(type_info, frag_spread)
            fields.update(resolved_frag.of.fields_dict)

    name = f"{concrete.name}__{path}"
    if ret := type_info.narrowed_types_map.get(name, None):
        return ret

    ret = QtGqlQueriedObjectType(
        name=name,
        concrete=concrete,
        fields_dict=fields,
    )
    type_info.narrowed_types_map[name] = ret
    return ret


def _evaluate_fragment(
    type_info: OperationTypeInfo,
    frag_spread: gql_lang.FragmentSpreadNode,
) -> QtGqlFragmentDefinition:
    # Generally fragments could have been evaluated globally
    # though we are evaluating them per operation
    # since in the future fragments might be scoped to an operation because of
    # https://github.com/graphql/graphql-spec/issues/204
    if evaluated := type_info.used_fragments.get(frag_spread.name.value, None):
        return evaluated
    raw_frag = type_info.raw_fragments[frag_spread.name.value]
    type_cond_name = raw_frag.type_condition.name.value
    frag_name = raw_frag.name.value
    fragment_of: QtGqlQueriedInterface | QtGqlQueriedObjectType
    if interface := type_info.schema_type_info.get_interface(type_cond_name):
        fragment_of = _evaluate_interface(
            type_info=type_info,
            concrete=interface,
            selection_set=raw_frag.selection_set,
            path=frag_name,
        )
    else:
        object_type = require(type_info.schema_type_info.get_object_type(type_cond_name))
        fragment_of = _evaluate_object_type(
            type_info=type_info,
            concrete=object_type,
            selection_set=raw_frag.selection_set,
            path=frag_name,
        )

    ret = QtGqlFragmentDefinition(
        name=frag_name,
        ast=raw_frag,
        of=fragment_of,
    )
    type_info.used_fragments[ret.name] = ret
    return ret


def _evaluate_operation(
    operation: OperationDefinitionNode,
    schema_type_info: SchemaTypeInfo,
    raw_fragments: dict[str, gql_lang.FragmentDefinitionNode],
) -> QtGqlOperationDefinition:
    """Each operation generates a whole new "proxy" schema. That schema will
    contain only the fields that are currently queried. The way we do that is
    creating a so-called "proxy objects".

    - Each proxy object mirrors a concrete object at schema level.
    - Each proxy object contains only the fields that was queried for this field in the tree.

    And because of that, one object type (at the concrete schema) might have many proxy objects.
    """
    type_info = OperationTypeInfo(schema_type_info, raw_fragments=raw_fragments)

    # input variables
    if variables_def := operation.variable_definitions:
        for var in variables_def:
            type_info.variables.append(_evaluate_variable(type_info.schema_type_info, var))

    selections = operation.selection_set
    root_type = type_info.schema_type_info.operation_types[operation.operation.value]
    assert root_type, f"Make sure you have {operation.operation.name} type defined in your schema"
    root_proxy_type = _evaluate_object_type(
        type_info=type_info,
        concrete=root_type,
        selection_set=selections,
        path="",
    )
    assert len(root_proxy_type.fields) == 1
    root_field = root_proxy_type.fields[0]
    return QtGqlOperationDefinition(
        root_field=root_field,
        root_type=root_proxy_type,
        operation_def=operation,
        variables=type_info.variables,
        narrowed_types=tuple(type_info.narrowed_types_map.values()),
        interfaces=tuple(type_info.narrowed_interfaces_map.values()),
        used_fragments=tuple(type_info.used_fragments.values()),
    )


class _OperationsVisitor(visitor.Visitor):
    def __init__(
        self,
        type_info: SchemaTypeInfo,
        fragments: dict[str, gql_lang.FragmentDefinitionNode],
    ):
        super().__init__()
        self.schema_type_info = type_info
        self.raw_fragments = fragments
        self.operations: dict[str, QtGqlOperationDefinition] = {}

    def enter_operation_definition(self, node: graphql.Node, *args, **kwargs) -> None:
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
                    self.raw_fragments,
                )


class _FragmentsVisitor(visitor.Visitor):
    """Gets all fragments from the operations file."""

    def __init__(self, type_info: SchemaTypeInfo):
        super().__init__()
        self.schema_type_info = type_info
        self.fragments: dict[str, gql_lang.FragmentDefinitionNode] = {}

    def enter_fragment_definition(self, node: graphql.Node, *args, **kwargs) -> None:
        fragment = require(is_fragment_definition_node(node))
        self.fragments[fragment.name.value] = fragment


def evaluate_operations(
    operations_document: graphql.DocumentNode,
    type_info: SchemaTypeInfo,
) -> dict[str, QtGqlOperationDefinition]:
    fragment_visitor = _FragmentsVisitor(type_info)
    graphql.visit(operations_document, fragment_visitor)
    operation_visitor = _OperationsVisitor(type_info, fragment_visitor.fragments)
    graphql.visit(operations_document, operation_visitor)
    assert operation_visitor.operations
    return operation_visitor.operations
