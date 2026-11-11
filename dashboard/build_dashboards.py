#!/usr/bin/env python3
"""Erzeugt die Grafana-Dashboards: ``python dashboard/build_dashboards.py``.

Die JSON-Dateien in ``dashboard/dashboards/`` sind generiert und werden mit committet
(ein Test prüft, dass sie aktuell sind). Keine Koordinaten, Kartenmittelpunkte oder
Zoomstufen eintragen – Karten nutzen „Fit to data“ (siehe scripts/check_dashboards.py).
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards"
DS = {"type": "grafana-postgresql-datasource", "uid": "flightdb"}
TZ = "'Europe/Berlin'"

EVENT_FILTER = """
  e.geofence_id IN (SELECT id FROM geofences WHERE name IN ($zone))
  AND e.category IN ($category)
  AND (e.relevant OR '$relevant' = 'alle')"""

SECTOR_ORDER = "array_position(ARRAY['N','NO','O','SO','S','SW','W','NW'], e.heading_sector)"
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


# --- Bausteine --------------------------------------------------------------------------


def target(sql: str, fmt: str = "table", ref: str = "A") -> dict:
    return {
        "refId": ref,
        "datasource": DS,
        "editorMode": "code",
        "format": fmt,
        "rawQuery": True,
        "rawSql": sql.strip(),
    }


def panel(kind: str, title: str, grid: tuple[int, int, int, int], targets: list[dict], **extra):
    x, y, w, h = grid
    p = {
        "type": kind,
        "title": title,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": targets,
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {},
    }
    for key, value in extra.items():
        p[key] = value
    return p


def stat(title, sql, grid, unit="none"):
    return panel(
        "stat",
        title,
        grid,
        [target(sql)],
        fieldConfig={"defaults": {"unit": unit}, "overrides": []},
        options={"reduceOptions": {"calcs": ["lastNotNull"], "values": False}},
    )


def query_var(name, label, sql, multi=True):
    return {
        "type": "query",
        "name": name,
        "label": label,
        "datasource": DS,
        "query": sql,
        "definition": sql,
        "refresh": 1,
        "multi": multi,
        "includeAll": multi,
        "current": {"text": "All", "value": "$__all"} if multi else {},
    }


def custom_var(name, label, values, default, multi=False, include_all=False):
    current = (
        {"text": "All", "value": "$__all"} if include_all else {"text": default, "value": default}
    )
    return {
        "type": "custom",
        "name": name,
        "label": label,
        "query": ",".join(values),
        "multi": multi,
        "includeAll": include_all,
        "current": current,
        "options": [{"text": v, "value": v, "selected": v == default} for v in values],
    }


def textbox_var(name, label, default=""):
    return {
        "type": "textbox",
        "name": name,
        "label": label,
        "query": default,
        "current": {"text": default, "value": default},
    }


def dashboard(uid, title, panels, variables, links=(), time_from="now-7d"):
    for i, p in enumerate(panels, start=1):
        p["id"] = i
    return {
        "uid": uid,
        "title": title,
        "tags": ["flightdb"],
        "timezone": "browser",
        "schemaVersion": 39,
        "editable": True,
        "time": {"from": time_from, "to": "now"},
        "templating": {"list": variables},
        "links": list(links),
        "panels": panels,
    }


def queries(d: dict) -> list[str]:
    out = [t["rawSql"] for p in d["panels"] for t in p.get("targets", [])]
    out += [v["query"] for v in d["templating"]["list"] if v["type"] == "query"]
    return out


# --- Dashboard „Überflüge“ --------------------------------------------------------------


def _count_since(since_sql: str) -> str:
    return (
        f"SELECT count(*) AS n FROM overflight_events e WHERE {EVENT_FILTER}\n"
        f"  AND e.entry_ts >= {since_sql}"
    )


def _hour_weekday_sql() -> str:
    hours = ",\n  ".join(
        f"count(*) FILTER (WHERE extract(hour FROM e.entry_ts AT TIME ZONE {TZ}) = {h})"
        f' AS "{h:02d}"'
        for h in range(24)
    )
    names = ", ".join(f"'{d}'" for d in WEEKDAYS)
    return f"""
SELECT (ARRAY[{names}])[extract(isodow FROM e.entry_ts AT TIME ZONE {TZ})::int] AS "Tag",
  {hours}
FROM overflight_events e
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}
GROUP BY extract(isodow FROM e.entry_ts AT TIME ZONE {TZ})
ORDER BY extract(isodow FROM e.entry_ts AT TIME ZONE {TZ})"""


def ueberfluege() -> dict:
    today = f"date_trunc('day', now() AT TIME ZONE {TZ}) AT TIME ZONE {TZ}"
    series = f"""
SELECT date_trunc('$bucket', e.entry_ts AT TIME ZONE {TZ}) AT TIME ZONE {TZ} AS time,
  e.category AS metric, count(*) AS value
FROM overflight_events e
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}
GROUP BY 1, 2 ORDER BY 1"""
    heights = f"""
SELECT to_char(floor(e.min_alt_ft / 1000.0) * 1000, 'FM99990') AS "ab ft", count(*) AS n
FROM overflight_events e
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER} AND e.min_alt_ft IS NOT NULL
GROUP BY floor(e.min_alt_ft / 1000.0) ORDER BY floor(e.min_alt_ft / 1000.0)"""
    sectors = f"""
SELECT e.heading_sector AS "Richtung", count(*) AS n
FROM overflight_events e
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER} AND e.heading_sector IS NOT NULL
GROUP BY e.heading_sector ORDER BY min({SECTOR_ORDER})"""
    categories = f"""
SELECT e.category AS "Kategorie", count(*) AS n
FROM overflight_events e
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}
GROUP BY 1 ORDER BY 1"""
    lowest = f"""
SELECT e.entry_ts AS "Zeit", f.callsign AS "Rufzeichen", f.icao24 AS "ICAO24",
  e.min_alt_ft AS "Höhe ft", round(e.min_dist_m) AS "Abstand m", e.category AS "Kategorie",
  g.name AS "Zone", e.n_positions_inside AS "Positionen",
  round(e.max_position_gap_s) AS "max. Lücke s",
  e.in_reception_gap AS "Empfangslücke", e.flight_id,
  (extract(epoch FROM f.first_ts) * 1000)::bigint AS t_from,
  (extract(epoch FROM f.last_ts) * 1000)::bigint AS t_to
FROM overflight_events e
JOIN flights f ON f.id = e.flight_id
JOIN geofences g ON g.id = e.geofence_id
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}
ORDER BY e.min_alt_ft NULLS LAST LIMIT 50"""
    heat = f"""
WITH ev AS (
  SELECT DISTINCT e.flight_id FROM overflight_events e
  WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}
)
SELECT round(ST_Y(d.geom)::numeric, 3)::float AS latitude,
  round(ST_X(d.geom)::numeric, 3)::float AS longitude, count(*) AS n
FROM flights f JOIN ev ON ev.flight_id = f.id, LATERAL ST_DumpPoints(f.track) d
GROUP BY 1, 2"""
    zone_outline = """
SELECT g.name AS zone, ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM geofences g, LATERAL ST_DumpPoints(g.geom) d
WHERE g.valid_to IS NULL AND g.name IN ($zone)"""
    coverage = """
SELECT 100 * sum(greatest(recorded_s - gap_s, 0)) / nullif(sum(day_s), 0) AS "%"
FROM data_coverage_daily
WHERE day BETWEEN ($__timeFrom())::timestamptz::date AND ($__timeTo())::timestamptz::date"""

    track_link = {
        "title": "Flugspur",
        "url": "/d/flightdb-flugspur/flugspur?var-flight_id=${__data.fields.flight_id}"
        "&from=${__data.fields.t_from}&to=${__data.fields.t_to}",
    }
    hidden = [
        {
            "matcher": {"id": "byName", "options": n},
            "properties": [{"id": "custom.hidden", "value": True}],
        }
        for n in ("flight_id", "t_from", "t_to")
    ]
    panels = [
        stat("Überflüge heute", _count_since(today), (0, 0, 4, 4)),
        stat("Überflüge 7 Tage", _count_since("now() - interval '7 days'"), (4, 0, 4, 4)),
        stat("Überflüge 30 Tage", _count_since("now() - interval '30 days'"), (8, 0, 4, 4)),
        stat(
            "Niedrigste Höhe im Zeitraum",
            f"SELECT min(e.min_alt_ft) AS ft FROM overflight_events e"
            f" WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}",
            (12, 0, 6, 4),
            unit="lengthft",
        ),
        stat("Empfangsabdeckung im Zeitraum", coverage, (18, 0, 6, 4), unit="percent"),
        panel(
            "timeseries",
            "Überflüge je Intervall (nach Kategorie)",
            (0, 4, 24, 8),
            [target(series, "time_series")],
            fieldConfig={
                "defaults": {
                    "custom": {
                        "drawStyle": "bars",
                        "fillOpacity": 80,
                        "stacking": {"mode": "normal"},
                    }
                },
                "overrides": [],
            },
        ),
        panel(
            "table",
            "Tageszeit × Wochentag",
            (0, 12, 24, 7),
            [target(_hour_weekday_sql())],
            fieldConfig={
                "defaults": {
                    "custom": {"cellOptions": {"type": "color-background"}},
                    "color": {"mode": "continuous-YlRd"},
                },
                "overrides": [],
            },
        ),
        panel(
            "barchart",
            "Höhenverteilung (niedrigste Höhe je Überflug)",
            (0, 19, 8, 8),
            [target(heights)],
            options={"xField": "ab ft"},
        ),
        panel(
            "barchart",
            "Flugrichtung",
            (8, 19, 8, 8),
            [target(sectors)],
            options={"xField": "Richtung"},
        ),
        panel(
            "piechart",
            "Kategorien (heuristisch)",
            (16, 19, 8, 8),
            [target(categories)],
            description="Anflug/Abflug ist eine Näherung aus Höhenverlauf und Abstand zu BER,"
            " keine Verfahrenszuordnung.",
            options={"reduceOptions": {"values": True, "calcs": []}},
        ),
        panel(
            "table",
            "Tiefste Überflüge",
            (0, 27, 24, 10),
            [target(lowest)],
            fieldConfig={
                "defaults": {},
                "overrides": hidden
                + [
                    {
                        "matcher": {"id": "byName", "options": "Rufzeichen"},
                        "properties": [{"id": "links", "value": [track_link]}],
                    }
                ],
            },
        ),
        panel(
            "geomap",
            "Spuren und Zonen",
            (0, 37, 24, 14),
            [target(heat, ref="A"), target(zone_outline, ref="B")],
            options={
                "view": {"id": "fit", "allLayers": True, "padding": 5},
                "controls": {"showZoom": True, "mouseWheelZoom": True},
                "basemap": {"type": "default", "name": "Karte"},
                "layers": [
                    {
                        "type": "heatmap",
                        "name": "Spuren",
                        "filterData": {"id": "byRefId", "options": "A"},
                        "location": {
                            "mode": "coords",
                            "latitude": "latitude",
                            "longitude": "longitude",
                        },
                        "config": {
                            "blur": 15,
                            "radius": 4,
                            "weight": {"field": "n", "fixed": 1, "min": 0, "max": 1},
                        },
                    },
                    {
                        "type": "markers",
                        "name": "Zonen",
                        "filterData": {"id": "byRefId", "options": "B"},
                        "location": {
                            "mode": "coords",
                            "latitude": "latitude",
                            "longitude": "longitude",
                        },
                        "config": {"style": {"size": {"fixed": 2}, "color": {"fixed": "dark-red"}}},
                    },
                ],
            },
        ),
    ]
    variables = [
        query_var(
            "zone", "Zone", "SELECT name FROM geofences WHERE valid_to IS NULL ORDER BY name"
        ),
        custom_var(
            "category",
            "Kategorie",
            ["arrival", "departure", "overflight", "unknown"],
            "arrival",
            multi=True,
            include_all=True,
        ),
        custom_var("relevant", "Überflüge", ["relevante", "alle"], "relevante"),
        custom_var("bucket", "Intervall", ["hour", "day", "week", "month"], "day"),
    ]
    return dashboard("flightdb-ueberfluege", "Überflüge", panels, variables)


# --- Dashboard „Datenqualität“ ----------------------------------------------------------


def datenqualitaet() -> dict:
    panels = [
        panel(
            "timeseries",
            "Empfangsabdeckung je Tag",
            (0, 0, 12, 8),
            [
                target(
                    f"""
SELECT day::timestamp AT TIME ZONE {TZ} AS time, receiver_id AS metric,
  100 * greatest(recorded_s - gap_s, 0) / nullif(day_s, 0) AS value
FROM data_coverage_daily
WHERE day BETWEEN ($__timeFrom())::timestamptz::date AND ($__timeTo())::timestamptz::date
ORDER BY 1""",
                    "time_series",
                )
            ],
            fieldConfig={"defaults": {"unit": "percent", "max": 100}, "overrides": []},
        ),
        panel(
            "timeseries",
            "Positionen je Stunde",
            (12, 0, 12, 8),
            [
                target(
                    """
SELECT date_trunc('hour', ts) AS time, count(*) AS value
FROM positions WHERE $__timeFilter(ts)
GROUP BY 1 ORDER BY 1""",
                    "time_series",
                )
            ],
        ),
        panel(
            "timeseries",
            "Dateien je Stunde",
            (0, 8, 12, 8),
            [
                target(
                    """
SELECT date_trunc('hour', period_start) AS time, status AS metric, count(*) AS value
FROM raw_files WHERE $__timeFilter(period_start)
GROUP BY 1, 2 ORDER BY 1""",
                    "time_series",
                )
            ],
        ),
        panel(
            "timeseries",
            "Uhrabweichung (max. je Datei)",
            (12, 8, 12, 8),
            [
                target(
                    """
SELECT period_start AS time, clock_offset_max_s AS value
FROM raw_files WHERE $__timeFilter(period_start) AND clock_offset_max_s IS NOT NULL
ORDER BY 1""",
                    "time_series",
                )
            ],
            fieldConfig={"defaults": {"unit": "s"}, "overrides": []},
        ),
        panel(
            "table",
            "Empfangslücken",
            (0, 16, 12, 9),
            [
                target("""
SELECT gap_start AS "Beginn", gap_end AS "Ende",
  round(extract(epoch FROM gap_end - gap_start)) AS "Dauer s", reason AS "Grund"
FROM reception_gaps WHERE $__timeFilter(gap_start)
ORDER BY gap_start DESC LIMIT 200""")
            ],
        ),
        panel("table", "Ingest-Status", (12, 16, 12, 4), [target("SELECT * FROM ingest_status")]),
        panel(
            "table",
            "Analyse-Läufe",
            (12, 20, 12, 9),
            [
                target("""
SELECT id, kind AS "Art", status, started_at AS "Beginn", finished_at AS "Ende",
  window_from AS "von", window_to AS "bis", n_flights AS "Flüge", n_events AS "Überflüge",
  n_skipped AS "übersprungen", error AS "Fehler"
FROM analysis_runs ORDER BY id DESC LIMIT 20""")
            ],
        ),
    ]
    variables = [textbox_var("tar1090", "tar1090-Adresse (lokal setzen)")]
    links = [
        {"title": "Live-Karte (tar1090)", "type": "link", "url": "${tar1090}", "targetBlank": True}
    ]
    return dashboard(
        "flightdb-datenqualitaet", "Datenqualität", panels, variables, links, time_from="now-2d"
    )


# --- Dashboard „Flugrouten“ -------------------------------------------------------------

# Bewertungen mit zugeordnetem Verfahren (Alias a, p) nach den Variablen des Dashboards.
ROUTE_FILTER = """
  $__timeFilter(a.ref_ts)
  AND p.name IN ($procedure)
  AND (a.confidence = 'high'
       OR (a.confidence = 'medium' AND '$confidence' <> 'nur hoch')
       OR '$confidence' = 'alle')
  AND (a.review OR '$only_review' = 'nein')"""

# Halbe Korridorbreite des letzten erfolgreichen Laufs (Standard 1852 m).
CORRIDOR_M = """coalesce((SELECT (params->>'corridor_m')::float8 FROM analysis_runs
    WHERE status = 'ok' ORDER BY id DESC LIMIT 1), 1852)"""

DIRECTION_COLORS = {
    "west": {"color": "blue", "index": 0, "text": "West"},
    "east": {"color": "orange", "index": 1, "text": "Ost"},
    "unknown": {"color": "#808080", "index": 2, "text": "unbekannt"},
}


def markers(name: str, ref: str, color: str, size: int = 2) -> dict:
    return {
        "type": "markers",
        "name": name,
        "filterData": {"id": "byRefId", "options": ref},
        "location": {"mode": "coords", "latitude": "latitude", "longitude": "longitude"},
        "config": {"style": {"size": {"fixed": size}, "color": {"fixed": color}}},
    }


def geomap(title: str, grid, targets: list[dict], layers: list[dict], padding: int = 5) -> dict:
    return panel(
        "geomap",
        title,
        grid,
        targets,
        options={
            "view": {"id": "fit", "allLayers": True, "padding": padding},
            "controls": {"showZoom": True, "mouseWheelZoom": True},
            "basemap": {"type": "default", "name": "Karte"},
            "layers": layers,
        },
    )


def _route_count(condition: str) -> str:
    return f"""
SELECT count(*) AS n
FROM flight_assessments a JOIN procedures p ON p.id = a.procedure_id
WHERE {ROUTE_FILTER}
  AND {condition}"""


def flugrouten() -> dict:
    rated = """
SELECT 100.0 * count(*) FILTER (WHERE a.confidence IN ('high', 'medium'))
  / nullif(count(*), 0) AS "%"
FROM flight_assessments a WHERE $__timeFilter(a.ref_ts)"""
    directions = """
SELECT window_start AS time, direction AS "Betriebsrichtung"
FROM operating_directions WHERE $__timeFilter(window_start) ORDER BY 1"""
    per_procedure = f"""
SELECT p.kind || ' ' || p.name AS "Verfahren", count(*) AS "Flüge",
  round(100.0 * count(*) FILTER (WHERE a.deviation) / count(*)) AS "Abw. %",
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY a.max_dev_m)) AS "Median m",
  round(percentile_cont(0.95) WITHIN GROUP (ORDER BY a.max_dev_m)) AS "95 % m"
FROM flight_assessments a JOIN procedures p ON p.id = a.procedure_id
WHERE {ROUTE_FILTER}
GROUP BY p.kind, p.name ORDER BY count(*) DESC"""
    valid = """p.superseded_at IS NULL AND p.name IN ($procedure)
  AND p.valid_from <= ($__timeTo())::timestamptz::date
  AND (p.valid_to IS NULL OR p.valid_to > ($__timeFrom())::timestamptz::date)"""
    ideal = f"""
SELECT p.name AS procedure, ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM procedures p,
  LATERAL ST_DumpPoints(ST_Segmentize(p.geom::geography, 200)::geometry) d
WHERE {valid}"""
    corridor = f"""
SELECT p.name AS procedure, ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM procedures p,
  LATERAL ST_DumpPoints(ST_Segmentize(ST_ExteriorRing(
    ST_Buffer(p.geom::geography, {CORRIDOR_M})::geometry)::geography, 200)::geometry) d
WHERE {valid}"""

    def tracks(review: bool) -> str:
        return f"""
WITH sel AS (
  SELECT a.flight_id FROM flight_assessments a JOIN procedures p ON p.id = a.procedure_id
  WHERE {ROUTE_FILTER} AND a.review = {str(review).lower()}
  ORDER BY a.ref_ts DESC LIMIT 100
)
SELECT f.id AS flight_id, ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM flights f JOIN sel ON sel.flight_id = f.id, LATERAL ST_DumpPoints(f.track) d
WHERE d.path[1] % 5 = 1"""

    reviews = f"""
SELECT a.ref_ts AS "Zeit", f.callsign AS "Rufzeichen", p.kind || ' ' || p.name AS "Verfahren",
  a.confidence AS "Sicherheit", round(a.max_dev_m) AS "max. Abw. m",
  round(a.outside_s) AS "außerhalb s",
  concat_ws(', ', CASE WHEN a.deviation THEN 'Abweichung' END,
    CASE WHEN a.approach THEN 'Annäherung' END) AS "Gründe",
  'Flugspur' AS "Flugspur", a.flight_id,
  (extract(epoch FROM f.first_ts) * 1000)::bigint AS t_from,
  (extract(epoch FROM f.last_ts) * 1000)::bigint AS t_to
FROM flight_assessments a
JOIN flights f ON f.id = a.flight_id
JOIN procedures p ON p.id = a.procedure_id
WHERE {ROUTE_FILTER} AND a.review
ORDER BY a.ref_ts DESC LIMIT 200"""

    track_link = {
        "title": "Flugspur",
        "url": "/d/flightdb-flugspur/flugspur?var-flight_id=${__data.fields.flight_id}"
        "&from=${__data.fields.t_from}&to=${__data.fields.t_to}",
    }
    hidden = [
        {
            "matcher": {"id": "byName", "options": n},
            "properties": [{"id": "custom.hidden", "value": True}],
        }
        for n in ("flight_id", "t_from", "t_to")
    ]
    panels = [
        stat("Bewertbar (Sicherheit ≥ mittel)", rated, (0, 0, 6, 4), unit="percent"),
        stat("Abweichungen (C)", _route_count("a.deviation"), (6, 0, 6, 4)),
        stat("Annäherungen (B)", _route_count("a.approach"), (12, 0, 6, 4)),
        stat("Prüffälle (E)", _route_count("a.review"), (18, 0, 6, 4)),
        panel(
            "state-timeline",
            "Betriebsrichtung",
            (0, 4, 24, 5),
            [target(directions)],
            fieldConfig={
                "defaults": {
                    "custom": {"insertNulls": 1800000},
                    "mappings": [{"type": "value", "options": DIRECTION_COLORS}],
                },
                "overrides": [],
            },
            options={"mergeValues": True, "showValue": "never"},
        ),
        panel("table", "Je Verfahren", (0, 9, 12, 12), [target(per_procedure)]),
        geomap(
            "Ideallinien, Korridor, Spuren",
            (12, 9, 12, 12),
            [
                target(ideal, ref="A"),
                target(corridor, ref="B"),
                target(tracks(False), ref="C"),
                target(tracks(True), ref="D"),
            ],
            [
                markers("Korridor", "B", "purple", 1),
                markers("Ideallinie", "A", "blue", 2),
                markers("Spuren", "C", "green", 1),
                markers("Prüffälle", "D", "red", 2),
            ],
        ),
        panel(
            "table",
            "Prüffälle",
            (0, 21, 24, 9),
            [target(reviews)],
            description="Eine Abweichung ist kein Verstoß: Radarführung und Freigaben sind aus"
            " ADS-B nicht erkennbar.",
            fieldConfig={
                "defaults": {},
                "overrides": hidden
                + [
                    {
                        "matcher": {"id": "byName", "options": "Flugspur"},
                        "properties": [{"id": "links", "value": [track_link]}],
                    }
                ],
            },
        ),
    ]
    variables = [
        query_var(
            "procedure",
            "Verfahren",
            "SELECT DISTINCT name FROM procedures WHERE superseded_at IS NULL ORDER BY name",
        ),
        custom_var("confidence", "Sicherheit", ["ab mittel", "nur hoch", "alle"], "ab mittel"),
        custom_var("only_review", "Nur Prüffälle", ["nein", "ja"], "nein"),
    ]
    return dashboard("flightdb-flugrouten", "Flugrouten", panels, variables)


# --- Dashboard „Flugspur“ ---------------------------------------------------------------

FLIGHT = "nullif(${flight_id:sqlstring}, '')::bigint"


def flugspur() -> dict:
    # Flug-ID aus der Textbox nur als SQL-Zeichenkette einsetzen und in bigint wandeln:
    # leere Eingabe ergibt keine Zeilen, beliebiger Text einen Typfehler statt SQL.
    assigned = f"p.id = (SELECT procedure_id FROM flight_assessments WHERE flight_id = {FLIGHT})"
    panels = [
        geomap(
            "Spur",
            (0, 0, 14, 14),
            [
                target(
                    f"""
SELECT ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude,
  to_timestamp(ST_M(d.geom)) AS time
FROM flights f, LATERAL ST_DumpPoints(f.track) d
WHERE f.id = {FLIGHT} ORDER BY d.path""",
                    ref="A",
                ),
                target(
                    f"""
SELECT ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM procedures p,
  LATERAL ST_DumpPoints(ST_Segmentize(p.geom::geography, 200)::geometry) d
WHERE {assigned}""",
                    ref="B",
                ),
                target(
                    f"""
SELECT ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM procedures p,
  LATERAL ST_DumpPoints(ST_Segmentize(ST_ExteriorRing(
    ST_Buffer(p.geom::geography, {CORRIDOR_M})::geometry)::geography, 200)::geometry) d
WHERE {assigned}""",
                    ref="C",
                ),
            ],
            [
                markers("Korridor", "C", "purple", 1),
                markers("Ideallinie", "B", "dark-blue", 2),
                markers("Spur", "A", "blue", 3),
            ],
            padding=10,
        ),
        panel(
            "table",
            "Überflüge dieses Flugs",
            (14, 0, 10, 14),
            [
                target(f"""
SELECT g.name AS "Zone", e.entry_ts AS "Eintritt", e.exit_ts AS "Austritt",
  e.min_alt_ft AS "Höhe ft", round(e.min_dist_m) AS "Abstand m", e.heading_sector AS "Richtung",
  e.category AS "Kategorie", e.category_basis::text AS "Begründung"
FROM overflight_events e JOIN geofences g ON g.id = e.geofence_id
WHERE e.flight_id = {FLIGHT} ORDER BY e.entry_ts""")
            ],
        ),
        panel(
            "timeseries",
            "Höhe und Geschwindigkeit",
            (0, 14, 24, 9),
            [
                target(
                    f"""
SELECT p.ts AS time, p.alt_baro_ft AS "Höhe ft", p.gs_kt AS "Geschwindigkeit kt"
FROM positions p JOIN flights f ON p.icao24 = f.icao24
  AND p.ts BETWEEN f.first_ts AND f.last_ts
WHERE f.id = {FLIGHT} ORDER BY 1""",
                    "time_series",
                )
            ],
        ),
        panel(
            "table",
            "Bewertung (Flugroutenvergleich)",
            (0, 23, 24, 6),
            [
                target(f"""
SELECT a.role AS "Rolle", a.direction AS "Betriebsrichtung", a.flight_sector AS "Sektor",
  p.kind || ' ' || p.name AS "Verfahren", a.confidence AS "Sicherheit",
  round(a.max_dev_m) AS "max. Abw. m", round(a.outside_s) AS "außerhalb s",
  a.deviation AS "Abweichung", a.approach AS "Annäherung", a.review AS "Prüffall",
  array_to_string(a.review_reasons, ', ') AS "erfüllt", a.basis AS "Begründung"
FROM flight_assessments a LEFT JOIN procedures p ON p.id = a.procedure_id
WHERE a.flight_id = {FLIGHT}""")
            ],
        ),
    ]
    variables = [textbox_var("flight_id", "Flug-ID", "0")]
    return dashboard("flightdb-flugspur", "Flugspur", panels, variables, time_from="now-24h")


def build() -> dict[str, dict]:
    return {
        "ueberfluege.json": ueberfluege(),
        "datenqualitaet.json": datenqualitaet(),
        "flugspur.json": flugspur(),
        "flugrouten.json": flugrouten(),
    }


def write(out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, d in build().items():
        (out / name).write_text(
            json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    write()
