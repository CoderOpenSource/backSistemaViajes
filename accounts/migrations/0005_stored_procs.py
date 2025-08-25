# accounts/migrations/0005_stored_procs.py
from django.db import migrations

# -----------------------------------------------------------
# ¿Qué hace esta migración?
# - Registra/actualiza 5 PROCEDIMIENTOS (CALL) útiles:
#   1) sp_user_deactivate                     → Desactivar usuario + auditar
#   2) sp_user_mark_password_changed          → Marcar cambio de contraseña + auditar
#   3) sp_user_force_pwd_change_by_role_office→ Forzar cambio de contraseña por rol/oficina (bulk) + auditar
#   4) sp_user_move_office_bulk               → Mover usuarios de una oficina a otra (bulk) + auditar
#   5) sp_auditlog_purge_older_than           → Borrar logs antiguos (housekeeping)
#
# - Registra 1 FUNCIÓN (SELECT) opcional:
#   fn_user_search_trgm                       → Búsqueda con trigram sobre username/email
#
# ¿Por qué en migración?
# - Para versionar el SQL y desplegar de forma reproducible en todos los entornos.
# -----------------------------------------------------------

SQL = r"""
-- ======================================================================
-- 1) Desactivar usuario + auditar
-- ======================================================================
CREATE OR REPLACE PROCEDURE sp_user_deactivate(
  p_user_id BIGINT,
  p_reason  TEXT DEFAULT 'deactivated by procedure'
)
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE "accounts_user"
  SET is_active = FALSE
  WHERE id = p_user_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'User % not found', p_user_id;
  END IF;

  INSERT INTO "accounts_auditlog"(user_id, action, entity, record_id, extra, created_at)
  VALUES (p_user_id, 'UPDATE', 'User', p_user_id::TEXT,
          jsonb_build_object('reason', p_reason, 'is_active', false),
          NOW());
END;
$$;

-- ======================================================================
-- 2) Marcar “cambio de contraseña realizado” + auditar
-- ======================================================================
CREATE OR REPLACE PROCEDURE sp_user_mark_password_changed(p_user_id BIGINT)
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE "accounts_user"
  SET last_password_change = NOW(),
      must_change_password = FALSE
  WHERE id = p_user_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'User % not found', p_user_id;
  END IF;

  INSERT INTO "accounts_auditlog"(user_id, action, entity, record_id, extra, created_at)
  VALUES (p_user_id, 'UPDATE', 'User', p_user_id::TEXT,
          jsonb_build_object('must_change_password', false, 'last_password_change', NOW()),
          NOW());
END;
$$;

-- ======================================================================
-- 3) Forzar cambio de contraseña por rol/oficina (bulk) + auditar
--     Si pasas NULL en role u office, ese filtro se ignora.
-- ======================================================================
CREATE OR REPLACE PROCEDURE sp_user_force_pwd_change_by_role_office(
  p_role TEXT DEFAULT NULL,
  p_office_id BIGINT DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_count INT;
BEGIN
  UPDATE "accounts_user" u
  SET must_change_password = TRUE
  WHERE is_active = TRUE
    AND (p_role IS NULL OR u.role = p_role)
    AND (p_office_id IS NULL OR u.office_id = p_office_id);

  GET DIAGNOSTICS v_count = ROW_COUNT;

  INSERT INTO "accounts_auditlog"(user_id, action, entity, record_id, extra, created_at)
  VALUES (NULL, 'UPDATE', 'User', 'BULK',
          jsonb_build_object('forced_pwd_change', true, 'role', p_role, 'office', p_office_id, 'count', v_count),
          NOW());
END;
$$;

-- ======================================================================
-- 4) Reasignar usuarios de una oficina a otra (bulk) + auditar
-- ======================================================================
CREATE OR REPLACE PROCEDURE sp_user_move_office_bulk(
  p_from_office BIGINT,
  p_to_office   BIGINT
)
LANGUAGE plpgsql
AS $$
DECLARE
  rec RECORD;
  cur CURSOR FOR
    SELECT id FROM "accounts_user" WHERE office_id = p_from_office;
BEGIN
  IF p_from_office = p_to_office THEN
    RAISE EXCEPTION 'Source and target office are the same';
  END IF;

  OPEN cur;
  LOOP
    FETCH cur INTO rec; EXIT WHEN NOT FOUND;

    UPDATE "accounts_user"
    SET office_id = p_to_office
    WHERE id = rec.id;

    INSERT INTO "accounts_auditlog"(user_id, action, entity, record_id, extra, created_at)
    VALUES (rec.id, 'UPDATE', 'User', rec.id::TEXT,
            jsonb_build_object('from_office', p_from_office, 'to_office', p_to_office),
            NOW());
  END LOOP;
  CLOSE cur;
END;
$$;

-- ======================================================================
-- 5) Depurar auditoría antigua (housekeeping)
-- ======================================================================
CREATE OR REPLACE PROCEDURE sp_auditlog_purge_older_than(p_days INT)
LANGUAGE plpgsql
AS $$
DECLARE
  v_cutoff TIMESTAMP := NOW() - (p_days || ' days')::INTERVAL;
  v_count  INT;
BEGIN
  DELETE FROM "accounts_auditlog" WHERE created_at < v_cutoff;
  GET DIAGNOSTICS v_count = ROW_COUNT;

  -- Opcional: resetear contadores y forzar nuevas estadísticas
  PERFORM pg_stat_reset_single_table_counters('public.accounts_auditlog'::regclass);
  ANALYZE "accounts_auditlog";

  RAISE NOTICE 'Audit rows purged: % (before %)', v_count, v_cutoff;
END;
$$;

-- ======================================================================
-- (OPCIONAL) FUNCIÓN de búsqueda con trigram (retorna filas)
--  Requiere extensión pg_trgm habilitada y GIN trigram en username/email.
-- ======================================================================
CREATE OR REPLACE FUNCTION fn_user_search_trgm(p_q TEXT, p_limit INT DEFAULT 20)
RETURNS TABLE(id BIGINT, username TEXT, email TEXT, score REAL)
LANGUAGE sql
AS $$
  SELECT id, username, email,
         GREATEST(similarity(username, p_q), similarity(email, p_q)) AS score
  FROM "accounts_user"
  WHERE p_q IS NOT NULL
    AND (username ILIKE '%'||p_q||'%' OR email ILIKE '%'||p_q||'%')
  ORDER BY score DESC
  LIMIT p_limit;
$$;
"""

# -----------------------------------------------------------
# reverse_sql: elimina procedimientos/función al hacer rollback
# (Debes indicar la firma exacta)
# -----------------------------------------------------------
REVERSE_SQL = r"""
DROP FUNCTION IF EXISTS fn_user_search_trgm(TEXT, INT);
DROP PROCEDURE IF EXISTS sp_auditlog_purge_older_than(INT);
DROP PROCEDURE IF EXISTS sp_user_move_office_bulk(BIGINT, BIGINT);
DROP PROCEDURE IF EXISTS sp_user_force_pwd_change_by_role_office(TEXT, BIGINT);
DROP PROCEDURE IF EXISTS sp_user_mark_password_changed(BIGINT);
DROP PROCEDURE IF EXISTS sp_user_deactivate(BIGINT, TEXT);
"""

class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_enable_trgm"),  # ajusta si tu última migración es otra
    ]
    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
    ]
