# catalog/migrations/000X_catalog_procs.py
from django.db import migrations

SQL = r"""
-- =========================================================
-- 1) Crear oficina
-- =========================================================
CREATE OR REPLACE PROCEDURE sp_office_create(
  p_code TEXT,
  p_name TEXT,
  p_department TEXT DEFAULT NULL,
  p_province TEXT DEFAULT NULL,
  p_municipality TEXT DEFAULT NULL,
  p_locality TEXT DEFAULT NULL,
  p_address TEXT DEFAULT NULL,
  p_phone TEXT DEFAULT NULL,
  p_location_url TEXT DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO catalog_office(
    code, name, department, province, municipality, locality,
    address, phone, location_url, active, created_at, updated_at
  )
  VALUES (p_code, p_name, p_department, p_province, p_municipality, p_locality,
          p_address, p_phone, p_location_url, TRUE, NOW(), NOW());
END;
$$;

-- =========================================================
-- 2) Desactivar oficina
-- =========================================================
CREATE OR REPLACE PROCEDURE sp_office_deactivate(p_office_id BIGINT)
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE catalog_office SET active = FALSE, updated_at = NOW()
  WHERE id = p_office_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Office % not found', p_office_id;
  END IF;
END;
$$;

-- =========================================================
-- 3) Registrar bus
-- =========================================================
CREATE OR REPLACE PROCEDURE sp_bus_register(
  p_code TEXT,
  p_model TEXT,
  p_year INT,
  p_plate TEXT,
  p_chassis TEXT,
  p_capacity INT
)
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO catalog_bus(code, model, year, plate, chassis_number, capacity, active, created_at)
  VALUES (p_code, p_model, p_year, p_plate, p_chassis, p_capacity, TRUE, NOW());
END;
$$;

-- =========================================================
-- 4) Desactivar bus
-- =========================================================
CREATE OR REPLACE PROCEDURE sp_bus_set_inactive(p_bus_id BIGINT)
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE catalog_bus SET active = FALSE
  WHERE id = p_bus_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Bus % not found', p_bus_id;
  END IF;
END;
$$;

-- =========================================================
-- 5) Crear ruta (origen != destino)
-- =========================================================
CREATE OR REPLACE PROCEDURE sp_route_create(
  p_name TEXT,
  p_origin BIGINT,
  p_destination BIGINT
)
LANGUAGE plpgsql
AS $$
BEGIN
  IF p_origin = p_destination THEN
    RAISE EXCEPTION 'Origin and destination must be different';
  END IF;

  INSERT INTO catalog_route(name, origin_id, destination_id, active, created_at)
  VALUES (p_name, p_origin, p_destination, TRUE, NOW());
END;
$$;

-- =========================================================
-- 6) Agregar parada a ruta
-- =========================================================
CREATE OR REPLACE PROCEDURE sp_route_add_stop(
  p_route_id BIGINT,
  p_office_id BIGINT,
  p_order INT,
  p_offset INT DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO catalog_routestop(route_id, office_id, "order", scheduled_offset_min)
  VALUES (p_route_id, p_office_id, p_order, p_offset);
END;
$$;

-- =========================================================
-- 7) Registrar tripulante
-- =========================================================
CREATE OR REPLACE PROCEDURE sp_crewmember_register(
  p_code TEXT,
  p_first TEXT,
  p_last TEXT,
  p_role TEXT,
  p_office BIGINT
)
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO catalog_crewmember(
    code, first_name, last_name, role, office_id,
    active, created_at, updated_at
  )
  VALUES (p_code, p_first, p_last, p_role, p_office, TRUE, NOW(), NOW());
END;
$$;

-- =========================================================
-- 8) Desactivar tripulante
-- =========================================================
CREATE OR REPLACE PROCEDURE sp_crewmember_deactivate(p_id BIGINT)
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE catalog_crewmember
  SET active = FALSE, updated_at = NOW()
  WHERE id = p_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'CrewMember % not found', p_id;
  END IF;
END;
$$;

-- =========================================================
-- 9) Crear licencia para chofer
-- =========================================================
CREATE OR REPLACE PROCEDURE sp_driverlicense_add(
  p_crewmember BIGINT,
  p_number TEXT,
  p_category TEXT,
  p_issued DATE,
  p_expires DATE
)
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO catalog_driverlicense(
    crew_member_id, number, category, issued_at, expires_at,
    active, notes
  )
  VALUES (p_crewmember, p_number, p_category, p_issued, p_expires, TRUE, '');
END;
$$;

-- =========================================================
-- 10) Crear departure (snapshot de capacidad)
-- =========================================================
CREATE OR REPLACE PROCEDURE sp_departure_create(
  p_route BIGINT,
  p_bus BIGINT,
  p_sched TIMESTAMP
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_capacity INT;
BEGIN
  SELECT capacity INTO v_capacity FROM catalog_bus WHERE id = p_bus;
  IF v_capacity IS NULL THEN
    RAISE EXCEPTION 'Bus % not found', p_bus;
  END IF;

  INSERT INTO catalog_departure(
    route_id, bus_id, scheduled_departure_at,
    status, capacity_snapshot, created_at
  )
  VALUES (p_route, p_bus, p_sched, 'SCHEDULED', v_capacity, NOW());
END;
$$;
"""

REVERSE_SQL = r"""
DROP PROCEDURE IF EXISTS sp_departure_create(BIGINT, BIGINT, TIMESTAMP);
DROP PROCEDURE IF EXISTS sp_driverlicense_add(BIGINT, TEXT, TEXT, DATE, DATE);
DROP PROCEDURE IF EXISTS sp_crewmember_deactivate(BIGINT);
DROP PROCEDURE IF EXISTS sp_crewmember_register(TEXT, TEXT, TEXT, TEXT, BIGINT);
DROP PROCEDURE IF EXISTS sp_route_add_stop(BIGINT, BIGINT, INT, INT);
DROP PROCEDURE IF EXISTS sp_route_create(TEXT, BIGINT, BIGINT);
DROP PROCEDURE IF EXISTS sp_bus_set_inactive(BIGINT);
DROP PROCEDURE IF EXISTS sp_bus_register(TEXT, TEXT, INT, TEXT, TEXT, INT);
DROP PROCEDURE IF EXISTS sp_office_deactivate(BIGINT);
DROP PROCEDURE IF EXISTS sp_office_create(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT);
"""

class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0007_alter_driverlicense_back_image_and_more"),
    ]
    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
    ]