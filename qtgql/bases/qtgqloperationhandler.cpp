#include "qtgqloperationhandler.hpp"

namespace qtgql {

void _QtGqlOperationHandlerBaseSignals::set_completed(bool v) {
  if (m_completed != v) {
    m_completed = v;
    emit completedChanged();
  }
  if (m_completed) {
    set_operation_on_flight(false);
  }
}
void _QtGqlOperationHandlerBaseSignals::set_operation_on_flight(bool v) {
  if (m_operation_on_the_fly != v) {
    m_operation_on_the_fly = v;
    emit operationOnFlightChanged();
  }
}

}  // namespace qtgql
