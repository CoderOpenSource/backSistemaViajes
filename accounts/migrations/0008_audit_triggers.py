# accounts/migrations/00XX_audit_triggers_all.py
from django.db import migrations

SQL_UP = r"""
-- ===========================================================
-- Función genérica de auditoría
-- ===========================================================
CREATE OR REPLACE FUNCTION auditlog_row_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_user_id   integer;
  v_username  text;
  v_ip        text;
  v_action    text;
  v_entity    text := TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME;
  v_record_id text;
  v_extra     jsonb := '{}'::jsonb;
BEGIN
  -- Contexto de aplicación (inyectado por middleware/vista)
  BEGIN v_user_id  := NULLIF(current_setting('app.user_id', true), '')::int; EXCEPTION WHEN others THEN v_user_id := NULL; END;
  BEGIN v_username := current_setting('app.user',    true); EXCEPTION WHEN others THEN v_username := NULL; END;
  BEGIN v_ip       := current_setting('app.ip',      true); EXCEPTION WHEN others THEN v_ip := NULL; END;

  IF TG_OP = 'INSERT' THEN
    v_action := 'CREATE';
    v_record_id := COALESCE((NEW).id::text, '');
    v_extra := jsonb_build_object('after', to_jsonb(NEW));
  ELSIF TG_OP = 'UPDATE' THEN
    v_action := 'UPDATE';
    v_record_id := COALESCE((NEW).id::text, (OLD).id::text, '');
    v_extra := jsonb_build_object('before', to_jsonb(OLD), 'after', to_jsonb(NEW));
  ELSIF TG_OP = 'DELETE' THEN
    v_action := 'DELETE';
    v_record_id := COALESCE((OLD).id::text, '');
    v_extra := jsonb_build_object('before', to_jsonb(OLD));
  END IF;

  v_extra := v_extra || jsonb_build_object(
    'schema', TG_TABLE_SCHEMA,
    'table',  TG_TABLE_NAME,
    'ip',     v_ip,
    'user',   v_username,
    'source', 'db_trigger'
  );

  INSERT INTO accounts_auditlog (user_id, action, entity, record_id, extra, created_at)
  VALUES (v_user_id, v_action, v_entity, v_record_id, v_extra, now());

  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  ELSE
    RETURN NEW;
  END IF;
END;
$$;

-- ===========================================================
-- Helper: asegura (drop/create) un trigger estándar sobre una tabla
-- ===========================================================
CREATE OR REPLACE FUNCTION ensure_audit_trigger(tab regclass, trig_name text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  -- Borra el trigger si ya existía con este nombre
  EXECUTE format('DROP TRIGGER IF EXISTS %I ON %s', trig_name, tab);

  -- Crea el trigger con la función de auditoría
  EXECUTE format(
    'CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %s
     FOR EACH ROW EXECUTE FUNCTION auditlog_row_change()',
     trig_name, tab
  );
END;
$$;

-- ===========================================================
-- (Re)crear triggers para TODAS las tablas objetivo
-- ===========================================================
DO $$
DECLARE t regclass;
BEGIN
  -- ACCOUNTS
  PERFORM ensure_audit_trigger('accounts_user'::regclass, 'trg_audit_accounts_user');

  -- CATALOG
  PERFORM ensure_audit_trigger('catalog_office'::regclass,               'trg_audit_catalog_office');
  PERFORM ensure_audit_trigger('catalog_bus'::regclass,                  'trg_audit_catalog_bus');
  PERFORM ensure_audit_trigger('catalog_seat'::regclass,                 'trg_audit_catalog_seat');
  PERFORM ensure_audit_trigger('catalog_route'::regclass,                'trg_audit_catalog_route');
  PERFORM ensure_audit_trigger('catalog_routestop'::regclass,            'trg_audit_catalog_routestop');
  PERFORM ensure_audit_trigger('catalog_departure'::regclass,            'trg_audit_catalog_departure');
  PERFORM ensure_audit_trigger('catalog_crewmember'::regclass,           'trg_audit_catalog_crewmember');
  PERFORM ensure_audit_trigger('catalog_driverlicense'::regclass,        'trg_audit_catalog_driverlicense');
  PERFORM ensure_audit_trigger('catalog_departureassignment'::regclass,  'trg_audit_catalog_departureassignment');

  -- PASSENGER
  PERFORM ensure_audit_trigger('passenger_passenger'::regclass,          'trg_audit_passenger_passenger');
  PERFORM ensure_audit_trigger('passenger_passengerrelation'::regclass,  'trg_audit_passenger_passengerrelation');

  -- SALES
  PERFORM ensure_audit_trigger('sales_ticket'::regclass,                 'trg_audit_sales_ticket');
  PERFORM ensure_audit_trigger('sales_payment'::regclass,                'trg_audit_sales_payment');
  PERFORM ensure_audit_trigger('sales_refund'::regclass,                 'trg_audit_sales_refund');
  PERFORM ensure_audit_trigger('sales_receipt'::regclass,                'trg_audit_sales_receipt');
END $$;
"""

SQL_DOWN = r"""
-- Borra triggers creados por esta migración
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT n.nspname AS schema, c.relname AS table, t.tgname
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE NOT t.tgisinternal
      AND t.tgname IN (
        'trg_audit_accounts_user',
        'trg_audit_catalog_office','trg_audit_catalog_bus','trg_audit_catalog_seat','trg_audit_catalog_route',
        'trg_audit_catalog_routestop','trg_audit_catalog_departure','trg_audit_catalog_crewmember',
        'trg_audit_catalog_driverlicense','trg_audit_catalog_departureassignment',
        'trg_audit_passenger_passenger','trg_audit_passenger_passengerrelation',
        'trg_audit_sales_ticket','trg_audit_sales_payment','trg_audit_sales_refund','trg_audit_sales_receipt'
      )
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I.%I', r.tgname, r.schema, r.table);
  END LOOP;
END $$;

-- Borra helpers/función
DROP FUNCTION IF EXISTS ensure_audit_trigger(regclass, text);
DROP FUNCTION IF EXISTS auditlog_row_change();
"""

# al final de accounts/migrations/0008_audit_triggers.py (o el número que uses)
class Migration(migrations.Migration):
    dependencies = [
        # encadena con la última migración existente en *accounts*
        ('accounts', '0006_functions'),

        # asegura que existan las tablas de los triggers antes de crearles el trigger
        ('catalog',   '0014_bus_photo1_bus_photo2_bus_photo3_bus_photo4'),
        ('passenger', '0003_remove_passenger_ix_passenger_nombres_trgm_and_more'),
        ('sales',     '0002_paymentmethod_payment_receipt_refund_and_more'),
    ]

    operations = [
        migrations.RunSQL(SQL_UP, SQL_DOWN),
    ]
