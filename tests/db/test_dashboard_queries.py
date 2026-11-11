import build_dashboards
import psycopg
import pytest
from dashboard_sql import substitute

pytestmark = pytest.mark.db


@pytest.mark.parametrize("name", sorted(build_dashboards.build()))
def test_all_queries_run_as_reader(db_dsns, name):
    dashboard = build_dashboards.build()[name]
    with psycopg.connect(db_dsns["reader"]) as c:
        for sql in build_dashboards.queries(dashboard):
            final = substitute(sql)
            assert "$" not in final, final
            c.execute(final)
            c.rollback()


def test_flugspur_empty_flight_id_gives_no_rows(db_dsns):
    dashboard = build_dashboards.build()["flugspur.json"]
    with psycopg.connect(db_dsns["reader"]) as c:
        for sql in build_dashboards.queries(dashboard):
            assert c.execute(substitute(sql, flight_id="")).fetchall() == []


@pytest.mark.parametrize("value", ["0 OR true", "0; SELECT 1", "x' OR 'a'='a"])
def test_flugspur_flight_id_is_not_sql(db_dsns, value):
    dashboard = build_dashboards.build()["flugspur.json"]
    with psycopg.connect(db_dsns["reader"]) as c:
        for sql in build_dashboards.queries(dashboard):
            with pytest.raises(psycopg.errors.InvalidTextRepresentation):
                c.execute(substitute(sql, flight_id=value))
            c.rollback()
