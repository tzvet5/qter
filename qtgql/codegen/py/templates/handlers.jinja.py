from qtgql.tools import slot, qproperty

{% import "macros.jinja.py" as macros %}

from typing import Optional, Union
from PySide6.QtCore import Signal, QObject
from PySide6.QtQml import QmlElement
from qtgql.codegen.py.runtime.queryhandler import (BaseQueryHandler,
                                                   QmlOperationConsumerABC,
                                                   SelectionConfig,
                                                   OperationMetaData,
                                                   BaseMutationHandler,
                                                   BaseSubscriptionHandler)
from qtgql.gqltransport.client import  GqlClientMessage, QueryPayload
from qtgql.codegen.py.runtime.bases import QGraphQListModel
from .objecttypes import * # noqa


QML_IMPORT_NAME = "generated.{{context.config.env_name}}"
QML_IMPORT_MAJOR_VERSION = 1


{% macro operation_classvars(operation_def) %}
    ENV_NAME = "{{context.config.env_name}}"
    OPERATION_METADATA = OperationMetaData(
        operation_name="{{operation_def.name}}",
        {% if operation_def.operation_config %}selections={{operation_def.operation_config}}{% endif %}
    )
    _message_template = GqlClientMessage(payload=QueryPayload(query="""{{operation_def.query}}""", operationName="{{operation_def.name}}"))
{% endmacro %}

{% macro operation_common(operation_def) %}
    def initialize(self) -> None:
        assert self._root_type
        self._root_type.{{operation_def.field.signal_name}}.connect(
            self.update_field
        )
        self.update_field()

    def on_data(self, message: dict) -> None:
        metadata = self.OPERATION_METADATA
        config = self.OPERATION_METADATA.selections
        parent = self
        root_type = {{operation_def.operation_type.name}}.from_dict(
            parent=parent,
            data=message,
            config=config,
            metadata=metadata,
        )

        if not self._root_type:
            self._root_type = root_type
            self.initialize()

    def update_field(self) -> None:
        assert self._root_type
        self._data = self._root_type.{{operation_def.field.private_name}}
        self.dataChanged.emit()



    def loose(self) -> None:
        metadata = self.OPERATION_METADATA
        assert self._root_type
        self._root_type.loose(metadata)

    {% if operation_def.variables %}
    @slot
    def setVariables(self,
                     {% for var in operation_def.variables %}{{var.name}}: {{var.annotation}}, {% endfor %}
                     ) -> None:
        {% for var in operation_def.variables %}
        if {{var.name}}:
            self._variables['{{var.name}}'] =  {{var.json_repr()}}
        {% endfor %}

    {% endif %}

{% endmacro %}


{% macro operation_consumer_common(operation) %}
    dataChanged = Signal()

    @qproperty(type=QObject, notify=dataChanged)
    def handlerData(self) -> {{operation.field.annotation}}:
        return self._handler._data
{% endmacro %}


{% for query in context.queries %}
class {{query.name}}(BaseQueryHandler[{{query.field.annotation}}, {{query.operation_type.name}}]):

    {{operation_classvars(query)}}
    {{operation_common(query)}}

@QmlElement
class Consume{{query.name}}(QmlOperationConsumerABC):
    {{operation_consumer_common(query)}}
    def _get_handler(self) -> BaseQueryHandler[{{query.field.annotation}}, {{query.operation_type.name}}]:
        return {{query.name}}(self)
{% endfor %}


{% for mutation in context.mutations %}
class {{mutation.name}}(BaseMutationHandler[{{mutation.field.annotation}}, {{mutation.operation_type.name}}]):

    {{operation_classvars(mutation)}}
    {{operation_common(mutation)}}

@QmlElement
class Consume{{mutation.name}}(QmlOperationConsumerABC[{{mutation.field.annotation}}, {{mutation.operation_type.name}}]):
    {{operation_consumer_common(mutation)}}

    def _get_handler(self) -> BaseMutationHandler[{{mutation.field.annotation}}]:
        return {{mutation.name}}(self)


{% endfor %}




{% for subscription in context.subscriptions %}
class {{subscription.name}}(BaseSubscriptionHandler[{{subscription.field.annotation}}, {{subscription.operation_type.name}}]):

    {{operation_classvars(subscription)}}
    {{operation_common(subscription)}}

@QmlElement
class Consume{{subscription.name}}(QmlOperationConsumerABC):
    {{operation_consumer_common(subscription)}}
    def _get_handler(self) -> BaseQueryHandler[{{subscription.field.annotation}}, {{subscription.operation_type.name}}]:
        return {{subscription.name}}(self)
{% endfor %}