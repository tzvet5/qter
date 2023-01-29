import strawberry


@strawberry.type
class User:
    name: str
    age: int
    age_point: float
    male: bool
    id: strawberry.ID


@strawberry.type
class Query:
    @strawberry.field
    def user(self) -> User:
        return User(name="Patrick", age=100, age_point=100.0, male=True, id=strawberry.ID("unique"))


schema = strawberry.Schema(query=Query)
