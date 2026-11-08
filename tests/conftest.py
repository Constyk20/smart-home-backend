"""Test setup.

If the real database and house modules cannot be imported (for example when these tests are
run outside the full project), light stand-ins are registered so the ML service code can still
be imported. Inside your project the real modules are used and nothing is replaced.
"""
import sys
import types


def _stub_if_missing() -> None:
    try:
        import app.db.mongodb  # noqa: F401
        import app.services.house_service  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    db_pkg = types.ModuleType("app.db")
    db_pkg.__path__ = []
    mongodb = types.ModuleType("app.db.mongodb")
    mongodb.get_database = lambda: None
    house = types.ModuleType("app.services.house_service")

    async def get_house_by_id(house_id, owner_id):
        return None

    house.get_house_by_id = get_house_by_id
    sys.modules.update(
        {"app.db": db_pkg, "app.db.mongodb": mongodb, "app.services.house_service": house}
    )


_stub_if_missing()
