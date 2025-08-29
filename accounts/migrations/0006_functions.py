# accounts/migrations/0006_functions.py
from django.db import migrations

# -----------------------------------------------------------------------------
# ¿Qué hace esta migración?
# Registra/actualiza 4 FUNCIONES (SELECT) útiles para accounts:
#
#  1) fn_user_can_login(username TEXT)
#       → Devuelve: (user_id, allowed, reason)
#         Razones: 'not_found' | 'inactive' | 'must_change_password' | 'ok'
#
#  2) fn_user_stats_by_role_office(p_only_active BOOL = true)
#       → Conteo por (role, office_id, office_code) para dashboards/reportes
#
#  3) fn_user_audit_trail(p_user_id BIGINT, p_limit INT = 50)
#       → Últimos N eventos de auditoría del usuario
#
#  4) fn_user_password_expired(p_user_id BIGINT, p_days INT = 90)
#       → TRUE si last_password_change es NULL o expirada (> p_days)
#
# Notas:
# - Todas las funciones son VOLATILE/READS SQL DATA (no escriben), excepto
#   ninguna aquí (todas son sólo lectura).
# - Se usan nombres de tablas: "accounts_user", "accounts_auditlog",
#   y "catalog_office" (join para office_code).
# -----------------------------------------------------------------------------

SQL = r"""
-- ============================================================================
-- 1) ¿Puede iniciar sesión? (por username)
--    Regresa el ID y el motivo por el que puede o no puede iniciar sesión.
-- ============================================================================
CREATE OR REPLACE FUNCTION fn_user_can_login(p_username TEXT)
RETURNS TABLE(user_id BIGINT, allowed BOOLEAN, reason TEXT)
LANGUAGE plpgsql
AS $$
DECLARE
  u RECORD;
BEGIN
  SELECT id, is_active, must_change_password
  INTO u
  FROM "accounts_user"
  WHERE username = p_username;

  IF NOT FOUND THEN
    RETURN QUERY SELECT NULL::BIGINT, FALSE, 'not_found';
    RETURN;
  END IF;

  IF u.is_active IS DISTINCT FROM TRUE THEN
    RETURN QUERY SELECT u.id::BIGINT, FALSE, 'inactive';
    RETURN;
  END IF;

  IF u.must_change_password THEN
    -- Permitimos el login, pero informamos que debe cambiar contraseña.
    RETURN QUERY SELECT u.id::BIGINT, TRUE, 'must_change_password';
    RETURN;
  END IF;

  RETURN QUERY SELECT u.id::BIGINT, TRUE, 'ok';
END;
$$;

COMMENT ON FUNCTION fn_user_can_login(TEXT) IS
'Valida login por username: not_found | inactive | must_change_password | ok';

-- ============================================================================
-- 2) Estadísticas por rol/oficina (opcionalmente sólo activos)
-- ============================================================================
CREATE OR REPLACE FUNCTION fn_user_stats_by_role_office(p_only_active BOOLEAN DEFAULT TRUE)
RETURNS TABLE(
  role TEXT,
  office_id BIGINT,
  office_code TEXT,
  users_count BIGINT
)
LANGUAGE sql
AS $$
  SELECT
    u.role::TEXT,
    u.office_id::BIGINT,
    o.code::TEXT AS office_code,
    COUNT(*)::BIGINT AS users_count
  FROM "accounts_user" u
  LEFT JOIN "catalog_office" o ON o.id = u.office_id
  WHERE (NOT p_only_active OR u.is_active = TRUE)
  GROUP BY u.role, u.office_id, o.code
  ORDER BY u.role, office_code NULLS LAST;
$$;

COMMENT ON FUNCTION fn_user_stats_by_role_office(BOOLEAN) IS
'Conteo de usuarios por (role, office_id, office_code); filtra sólo activos si TRUE.';

-- ============================================================================
-- 3) Últimos N eventos de auditoría de un usuario
-- ============================================================================
CREATE OR REPLACE FUNCTION fn_user_audit_trail(p_user_id BIGINT, p_limit INT DEFAULT 50)
RETURNS TABLE(
  id BIGINT,
  action TEXT,
  entity TEXT,
  record_id TEXT,
  extra JSONB,
  created_at TIMESTAMP WITH TIME ZONE
)
LANGUAGE sql
AS $$
  SELECT
    a.id::BIGINT,
    a.action::TEXT,
    a.entity::TEXT,
    a.record_id::TEXT,
    a.extra,
    a.created_at
  FROM "accounts_auditlog" a
  WHERE a.user_id = p_user_id
  ORDER BY a.created_at DESC
  LIMIT p_limit;
$$;

COMMENT ON FUNCTION fn_user_audit_trail(BIGINT, INT) IS
'Devuelve los últimos N eventos de auditoría para un usuario específico.';

-- ============================================================================
-- 4) ¿Contraseña expirada?
--    TRUE si last_password_change es NULL o anterior a NOW() - p_days.
-- ============================================================================
CREATE OR REPLACE FUNCTION fn_user_password_expired(p_user_id BIGINT, p_days INT DEFAULT 90)
RETURNS BOOLEAN
LANGUAGE sql
AS $$
  SELECT
    CASE
      WHEN u.id IS NULL THEN TRUE                     -- usuario inexistente => tratar como expirado
      WHEN u.last_password_change IS NULL THEN TRUE   -- nunca cambió
      WHEN u.last_password_change < (NOW() - (p_days || ' days')::INTERVAL) THEN TRUE
      ELSE FALSE
    END
  FROM "accounts_user" u
  WHERE u.id = p_user_id;
$$;

COMMENT ON FUNCTION fn_user_password_expired(BIGINT, INT) IS
'Indica si la contraseña está expirada según p_days (por defecto 90 días).';
"""

REVERSE_SQL = r"""
DROP FUNCTION IF EXISTS fn_user_password_expired(BIGINT, INT);
DROP FUNCTION IF EXISTS fn_user_audit_trail(BIGINT, INT);
DROP FUNCTION IF EXISTS fn_user_stats_by_role_office(BOOLEAN);
DROP FUNCTION IF EXISTS fn_user_can_login(TEXT);
"""

class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_stored_procs"),  # Asegúrate que exista; ajusta si tu última es otra
    ]

    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
    ]
