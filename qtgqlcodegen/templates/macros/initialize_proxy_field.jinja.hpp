{% macro initialize_proxy_field(field, operation_pointer = "operation") -%}
{%set instance_of_concrete -%}
m_inst->👉field.concrete.getter_name 👈(👉field.build_variables_tuple_for_field_arguments 👈)
{% endset -%}

{% if field.type.is_queried_object_type  and field.type.is_optional %}
if (👉 instance_of_concrete 👈){
👉field.private_name👈 = new 👉field.type_name👈(👉operation_pointer👈, 👉 instance_of_concrete 👈);
}
else{
👉field.private_name👈 = nullptr; // TODO: this is probably redundant
}
{% elif field.type.is_queried_object_type %}
👉field.private_name👈 = new 👉field.type_name👈(👉operation_pointer👈, 👉 instance_of_concrete 👈);
{% elif field.type.is_model and field.type.is_model.of_type.is_queried_object_type %}
auto init_list_👉 field.name 👈 =  std::make_unique<QList<👉field.type.of_type.name👈*>>();
for (const auto & node: 👉 instance_of_concrete 👈){
init_list_👉 field.name 👈->append(new 👉field.type.of_type.name👈(👉operation_pointer👈, node));
}
👉field.private_name👈 = new qtgql::bases::ListModelABC<👉 field.type.of_type.name 👈>(this, std::move(init_list_👉 field.name 👈));
{% elif field.type.is_queried_interface %}
auto concrete_👉field.name👈 = 👉 instance_of_concrete 👈;
auto type_name = concrete_👉field.name👈->TYPE_NAME();
{% for choice in field.type.choices -%}
if (type_name == "👉 choice.concrete.name 👈"){
👉field.private_name👈 = qobject_cast<👉 field.type.name 👈*>(new 👉choice.type_name()👈(👉operation_pointer👈, std::static_pointer_cast<👉 choice.concrete.name 👈>(concrete_👉field.name👈)));
}
{% endfor %}
{% endif -%}
{% endmacro -%}