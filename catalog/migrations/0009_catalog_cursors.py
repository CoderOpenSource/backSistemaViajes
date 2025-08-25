# catalog/migrations/0009_catalog_cursors.py
from django.db import migrations

SQL = r"""
/* =========================================================
   1) Desactivar licencias vencidas (cursor por licencia)
   ========================================================= */
CREATE OR REPLACE PROCEDURE sp_driverlicense_deactivate_expired(p_on DATE)
LANGUAGE plpgsql
AS $$
DECLARE
  r RECORD;
  c CURSOR FOR
    SELECT id
    FROM catalog_driverlicense
    WHERE active = TRUE
      AND expires_at IS NOT NULL
      AND expires_at < p_on;
BEGIN
  OPEN c;
  LOOP
    FETCH c INTO r; EXIT WHEN NOT FOUND;

    UPDATE catalog_driverlicense
    SET active = FALSE,
        notes  = COALESCE(notes,'') || CASE WHEN notes IS NULL OR notes = '' THEN '' ELSE ' ' END
                || '[expired:' || to_char(p_on,'YYYY-MM-DD') || ']'
    WHERE id = r.id;
  END LOOP;
  CLOSE c;
END;
$$;

/* =========================================================
   2) Desactivar DRIVERS sin licencia válida a una fecha,
      filtrando por oficina (cursor por empleado)
   ========================================================= */
CREATE OR REPLACE PROCEDURE sp_drivers_deactivate_without_valid_license(
  p_office_id BIGINT,
  p_on TIMESTAMP
)
LANGUAGE plpgsql
AS $$
DECLARE
  r RECORD;
  c CURSOR FOR
    SELECT id
    FROM catalog_crewmember
    WHERE active = TRUE
      AND role = 'DRIVER'
      AND (p_office_id IS NULL OR office_id = p_office_id);
  has_valid BOOLEAN;
BEGIN
  OPEN c;
  LOOP
    FETCH c INTO r; EXIT WHEN NOT FOUND;

    /* ¿Tiene alguna licencia válida en p_on ? */
    SELECT EXISTS (
      SELECT 1
      FROM catalog_driverlicense dl
      WHERE dl.crew_member_id = r.id
        AND dl.active = TRUE
        AND (dl.issued_at IS NULL OR dl.issued_at <= p_on::date)
        AND (dl.expires_at IS NULL OR dl.expires_at >= p_on::date)
    ) INTO has_valid;

    IF NOT has_valid THEN
      UPDATE catalog_crewmember
      SET active = FALSE,
          updated_at = NOW()
      WHERE id = r.id;
    END IF;
  END LOOP;
  CLOSE c;
END;
$$;

/* =========================================================
   3) Reasignar empleados por rol de una oficina a otra
      (cursor por empleado)
   ========================================================= */
CREATE OR REPLACE PROCEDURE sp_crewmember_move_office_by_role(
  p_from_office BIGINT,
  p_to_office   BIGINT,
  p_role        TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
  r RECORD;
  c CURSOR FOR
    SELECT id
    FROM catalog_crewmember
    WHERE active = TRUE
      AND office_id = p_from_office
      AND (p_role IS NULL OR role = p_role);
BEGIN
  IF p_from_office = p_to_office THEN
    RAISE EXCEPTION 'Source and target office are the same';
  END IF;

  OPEN c;
  LOOP
    FETCH c INTO r; EXIT WHEN NOT FOUND;

    UPDATE catalog_crewmember
    SET office_id = p_to_office,
        updated_at = NOW()
    WHERE id = r.id;
  END LOOP;
  CLOSE c;
END;
$$;

/* =========================================================
   4) Cerrar departures antiguos (cursor por departure)
      Estados a cerrar: SCHEDULED / BOARDING / DEPARTED
   ========================================================= */
CREATE OR REPLACE PROCEDURE sp_departures_close_past(p_until TIMESTAMP)
LANGUAGE plpgsql
AS $$
DECLARE
  r RECORD;
  c CURSOR FOR
    SELECT id
    FROM catalog_departure
    WHERE scheduled_departure_at < p_until
      AND status IN ('SCHEDULED','BOARDING','DEPARTED');
BEGIN
  OPEN c;
  LOOP
    FETCH c INTO r; EXIT WHEN NOT FOUND;

    UPDATE catalog_departure
    SET status = 'CLOSED'
    WHERE id = r.id;
  END LOOP;
  CLOSE c;
END;
$$;

/* =========================================================
   5) Desactivar oficina si no tiene personal activo
      (cursor para detectar al menos 1 empleado activo)
   ========================================================= */
CREATE OR REPLACE PROCEDURE sp_office_deactivate_if_no_active_staff(p_office_id BIGINT)
LANGUAGE plpgsql
AS $$
DECLARE
  r RECORD;
  c CURSOR FOR
    SELECT id FROM catalog_crewmember
    WHERE office_id = p_office_id AND active = TRUE;
BEGIN
  OPEN c;
  FETCH c INTO r;
  IF NOT FOUND THEN
    UPDATE catalog_office
    SET active = FALSE, updated_at = NOW()
    WHERE id = p_office_id;
  END IF;
  CLOSE c;
END;
$$;
"""

REVERSE_SQL = r"""
DROP PROCEDURE IF EXISTS sp_office_deactivate_if_no_active_staff(BIGINT);
DROP PROCEDURE IF EXISTS sp_departures_close_past(TIMESTAMP);
DROP PROCEDURE IF EXISTS sp_crewmember_move_office_by_role(BIGINT, BIGINT, TEXT);
DROP PROCEDURE IF EXISTS sp_drivers_deactivate_without_valid_license(BIGINT, TIMESTAMP);
DROP PROCEDURE IF EXISTS sp_driverlicense_deactivate_expired(DATE);
"""

class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0008_catalog_procs"),  # ajusta si tu numeración es distinta
    ]
    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
    ]
