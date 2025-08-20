from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from accounts.permissions_map import PERMISSIONS_BY_GROUP, ADMIN_FLAGS

User = get_user_model()

class Command(BaseCommand):
    help = "Crea/actualiza grupos (Admin, Vendedor, Cajero) y asigna permisos según PERMISSIONS_BY_GROUP."

    def handle(self, *args, **options):
        created_groups = 0
        for group_name in PERMISSIONS_BY_GROUP.keys():
            _, created = Group.objects.get_or_create(name=group_name)
            created_groups += int(created)
        self.stdout.write(self.style.SUCCESS(f"Grupos verificados: {', '.join(PERMISSIONS_BY_GROUP.keys())} (nuevos: {created_groups})"))

        for group_name, conf in PERMISSIONS_BY_GROUP.items():
            group = Group.objects.get(name=group_name)
            if conf.get("ALL"):
                perms = Permission.objects.all()
                group.permissions.set(perms)
                self.stdout.write(f"• {group_name}: ALL permissions asignados ({perms.count()})")
                continue

            # Construir set de permisos desde el mapeo app -> modelo -> codenames
            final_perms = set()
            for app_label, models_map in conf.items():
                if app_label == "ALL":
                    continue
                for model_name, codename_list in models_map.items():
                    if not codename_list:
                        continue
                    try:
                        ct = ContentType.objects.get(app_label=app_label, model=model_name)
                    except ContentType.DoesNotExist:
                        self.stdout.write(self.style.WARNING(f"  ⚠ No existe ContentType {app_label}.{model_name} (aún). Saltando..."))
                        continue
                    perms = Permission.objects.filter(content_type=ct, codename__in=codename_list)
                    final_perms.update(list(perms))

            group.permissions.set(final_perms)
            self.stdout.write(f"• {group_name}: {len(final_perms)} permisos asignados.")

        # Asegurar flags para usuarios con role=ADMIN
        admins = User.objects.filter(role="ADMIN")
        updated = 0
        for u in admins:
            changed = False
            for field, val in ADMIN_FLAGS.items():
                if getattr(u, field) != val:
                    setattr(u, field, val)
                    changed = True
            if changed:
                u.save(update_fields=list(ADMIN_FLAGS.keys()))
                updated += 1
        self.stdout.write(self.style.SUCCESS(f"Admins actualizados con flags {ADMIN_FLAGS}: {updated}"))
        self.stdout.write(self.style.SUCCESS("Listo ✅"))
