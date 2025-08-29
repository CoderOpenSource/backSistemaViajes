# catalog/migrations/0012_catalog_functions.py
from django.db import migrations

SQL = r"""
-- =====================================================================
-- 1) Secuencia de paradas de una ruta con datos de oficina
-- =====================================================================
CREATE OR REPLACE FUNCTION fn_route_stops(p_route_id BIGINT)
RETURNS TABLE(
  order_n INT,
  office_id BIGINT,
  office_code TEXT,
  office_name TEXT,
  offset_min INT
)
LANGUAGE sql
AS $$
  SELECT
    rs."order"::INT        AS order_n,
    rs.office_id::BIGINT   AS office_id,
    o.code::TEXT           AS office_code,
    o.name::TEXT           AS office_name,
    rs.scheduled_offset_min::INT AS offset_min
  FROM catalog_routestop rs
  JOIN catalog_office o ON o.id = rs.office_id
  WHERE rs.route_id = p_route_id
  ORDER BY rs."order";
$$;

COMMENT ON FUNCTION fn_route_stops(BIGINT) IS
'Devuelve la secuencia (order, office_code/name, offset) de una ruta.';

-- =====================================================================
-- 2) Duración/offset total de una ruta (máximo offset)
--     Si no hay offsets definidos, devuelve 0.
-- =====================================================================
CREATE OR REPLACE FUNCTION fn_route_total_offset(p_route_id BIGINT)
RETURNS INT
LANGUAGE sql
AS $$
  SELECT COALESCE(MAX(rs.scheduled_offset_min), 0)::INT
  FROM catalog_routestop rs
  WHERE rs.route_id = p_route_id;
$$;

COMMENT ON FUNCTION fn_route_total_offset(BIGINT) IS
'Máximo offset (min) de las paradas de la ruta; 0 si no hay.';

-- =====================================================================
-- 3) Cronograma programado de un Departure (fecha/hora por parada)
--     Calcula scheduled_at = scheduled_departure_at + offset(min)
-- =====================================================================
CREATE OR REPLACE FUNCTION fn_departure_timetable(p_departure_id BIGINT)
RETURNS TABLE(
  order_n INT,
  office_id BIGINT,
  office_code TEXT,
  office_name TEXT,
  scheduled_at TIMESTAMPTZ
)
LANGUAGE sql
AS $$
  SELECT
    rs."order"::INT              AS order_n,
    rs.office_id::BIGINT         AS office_id,
    o.code::TEXT                 AS office_code,
    o.name::TEXT                 AS office_name,
    (d.scheduled_departure_at
      + COALESCE(rs.scheduled_offset_min, 0) * INTERVAL '1 minute')::timestamptz AS scheduled_at
  FROM catalog_departure d
  JOIN catalog_route r       ON r.id = d.route_id
  JOIN catalog_routestop rs  ON rs.route_id = r.id
  JOIN catalog_office o      ON o.id = rs.office_id
  WHERE d.id = p_departure_id
  ORDER BY rs."order";
$$;

COMMENT ON FUNCTION fn_departure_timetable(BIGINT) IS
'Devuelve (order, oficina, hora programada por parada) para un departure.';

-- =====================================================================
-- 4) ¿Está disponible un bus en torno a una fecha/hora?
--     Verifica colisiones con ventana ±p_window_min (default 30)
--     Ignora departures CANCELLED.
-- =====================================================================
CREATE OR REPLACE FUNCTION fn_bus_is_available(
  p_bus_id BIGINT,
  p_at TIMESTAMPTZ,
  p_window_min INT DEFAULT 30
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
  v_start TIMESTAMPTZ := p_at - (p_window_min || ' minutes')::interval;
  v_end   TIMESTAMPTZ := p_at + (p_window_min || ' minutes')::interval;
  v_exists BOOLEAN;
BEGIN
  SELECT EXISTS (
    SELECT 1
    FROM catalog_departure d
    WHERE d.bus_id = p_bus_id
      AND d.status <> 'CANCELLED'
      AND d.scheduled_departure_at BETWEEN v_start AND v_end
  ) INTO v_exists;

  RETURN NOT v_exists;
END;
$$;

COMMENT ON FUNCTION fn_bus_is_available(BIGINT, TIMESTAMPTZ, INT) IS
'TRUE si no hay colisiones de agenda del bus en ±window_min desde p_at.';

-- =====================================================================
-- 5) Contadores rápidos de catálogo (para dashboards)
--     p_only_active: si TRUE sólo cuenta activos cuando aplique.
-- =====================================================================
CREATE OR REPLACE FUNCTION fn_catalog_counters(p_only_active BOOLEAN DEFAULT TRUE)
RETURNS TABLE(metric TEXT, count BIGINT)
LANGUAGE sql
AS $$
  -- Offices
  SELECT 'offices'::TEXT AS metric,
         COUNT(*)::BIGINT AS count
  FROM catalog_office o
  WHERE (NOT p_only_active OR o.active = TRUE)

  UNION ALL
  -- Buses
  SELECT 'buses'::TEXT,
         COUNT(*)::BIGINT
  FROM catalog_bus b
  WHERE (NOT p_only_active OR b.active = TRUE)

  UNION ALL
  -- Routes
  SELECT 'routes'::TEXT,
         COUNT(*)::BIGINT
  FROM catalog_route r
  WHERE (NOT p_only_active OR r.active = TRUE)

  UNION ALL
  -- CrewMembers
  SELECT 'crew_members'::TEXT,
         COUNT(*)::BIGINT
  FROM catalog_crewmember c
  WHERE (NOT p_only_active OR c.active = TRUE)

  UNION ALL
  -- Departures futuras (no canceladas)
  SELECT 'departures_upcoming'::TEXT,
         COUNT(*)::BIGINT
  FROM catalog_departure d
  WHERE d.scheduled_departure_at >= NOW()
    AND d.status <> 'CANCELLED';
$$;

COMMENT ON FUNCTION fn_catalog_counters(BOOLEAN) IS
'Filas (metric, count) con totales: offices, buses, routes, crew, departures_upcoming.';
"""

REVERSE_SQL = r"""
DROP FUNCTION IF EXISTS fn_catalog_counters(BOOLEAN);
DROP FUNCTION IF EXISTS fn_bus_is_available(BIGINT, TIMESTAMPTZ, INT);
DROP FUNCTION IF EXISTS fn_departure_timetable(BIGINT);
DROP FUNCTION IF EXISTS fn_route_total_offset(BIGINT);
DROP FUNCTION IF EXISTS fn_route_stops(BIGINT);
"""

class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0011_alter_departure_driver_and_more"),  # ajusta si tu última difiere
    ]
    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
    ]
