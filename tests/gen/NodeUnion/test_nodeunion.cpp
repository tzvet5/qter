#include "gen/MainQuery.hpp"
#include "testframework.hpp"
#include "testutils.hpp"
#include <QSignalSpy>

namespace NodeUnion {
using namespace qtgql;

auto ENV_NAME = std::string("NodeUnion");
auto SCHEMA_ADDR =
    test_utils::get_server_address(QString::fromStdString(ENV_NAME));

TEST_CASE("NodeUnion") {
  auto env = test_utils::get_or_create_env(
      ENV_NAME,
      test_utils::DebugWsClientSettings{.prod_settings = {.url = SCHEMA_ADDR}});

  auto mq = mainquery::MainQuery::shared();
  mq->set_variables({Enums::UnionChoice::PERSON});
  mq->execute();
  test_utils::wait_for_completion(mq);
  SECTION("test deserialize") {
    auto raw_ptr = mq->data()->get_whoAmI();
    REQUIRE(raw_ptr->property("__typeName").toString().toStdString() ==
            "Person");
    auto p = qobject_cast<const mainquery::Person__whoAmI *>(raw_ptr);
    REQUIRE(!p->get_name().isEmpty());
  };
  SECTION("test update same type") {
    auto person = qobject_cast<const mainquery::Person__whoAmI *>(
        mq->data()->get_whoAmI());
    auto prev_name = mq->data()->get_whoAmI()->property("name").toString();
    auto mq2 = mainquery::MainQuery::shared();
    test_utils::SignalCatcher catcher({.source_obj = person, .only = "name"});
    mq2->set_variables({Enums::UnionChoice::PERSON});
    mq2->execute();
    REQUIRE(catcher.wait());
    test_utils::wait_for_completion(mq2);
    REQUIRE(mq->data()

                ->get_whoAmI()
                ->property("name")
                .toString()
                .toStdString() != prev_name.toStdString());
  };
  SECTION("test update different type") {
    auto root = mq->data();
    test_utils::SignalCatcher catcher({.source_obj = root, .only = "whoAmI"});
    mq->set_variables({Enums::UnionChoice::FROG});
    mq->execute();
    REQUIRE(catcher.wait());
    test_utils::wait_for_completion(mq);
    auto frog_maybe = root->get_whoAmI();
    REQUIRE(frog_maybe->__typename().toStdString() == "Frog");
    REQUIRE(!qobject_cast<const mainquery::Frog__whoAmI *>(frog_maybe)
                 ->get_color()
                 .isEmpty());
  }
}
}; // namespace NodeUnion
