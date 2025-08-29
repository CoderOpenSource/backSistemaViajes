# users/management/commands/seed_users.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from catalog.models import Office

User = get_user_model()

SEED_USERS = [
    # --- Admins ---
    {
        "username": "admin2",
        "email": "admin2@example.com",
        "password": "Admin123!",
        "role": "ADMIN",
        "office_code": "SCZ-01",
    },
    {
        "username": "supervisor",
        "email": "supervisor@example.com",
        "password": "Supervisor123!",
        "role": "ADMIN",
        "office_code": "CBB-01",
    },

    # --- Vendedores ---
    {
        "username": "vend_lpz1",
        "email": "vend_lpz1@example.com",
        "password": "Vendedor123!",
        "role": "VEND",
        "office_code": "LPZ-01",
    },
    {
        "username": "vend_lpz2",
        "email": "vend_lpz2@example.com",
        "password": "Vendedor123!",
        "role": "VEND",
        "office_code": "LPZ-02",
    },
    {
        "username": "vend_scz1",
        "email": "vend_scz1@example.com",
        "password": "Vendedor123!",
        "role": "VEND",
        "office_code": "SCZ-02",
    },
    {
        "username": "vend_scz2",
        "email": "vend_scz2@example.com",
        "password": "Vendedor123!",
        "role": "VEND",
        "office_code": "SCZ-04",
    },
    {
        "username": "vend_cbb1",
        "email": "vend_cbb1@example.com",
        "password": "Vendedor123!",
        "role": "VEND",
        "office_code": "CBB-02",
    },
    {
        "username": "vend_oru1",
        "email": "vend_oru1@example.com",
        "password": "Vendedor123!",
        "role": "VEND",
        "office_code": "ORU-01",
    },
    {
        "username": "vend_pts1",
        "email": "vend_pts1@example.com",
        "password": "Vendedor123!",
        "role": "VEND",
        "office_code": "PTS-01",
    },
    {
        "username": "vend_trj1",
        "email": "vend_trj1@example.com",
        "password": "Vendedor123!",
        "role": "VEND",
        "office_code": "TRJ-01",
    },

    # --- Cajeros ---
    {
        "username": "caj_lpz1",
        "email": "caj_lpz1@example.com",
        "password": "Cajero123!",
        "role": "CAJE",
        "office_code": "LPZ-03",
    },
    {
        "username": "caj_lpz2",
        "email": "caj_lpz2@example.com",
        "password": "Cajero123!",
        "role": "CAJE",
        "office_code": "LPZ-04",
    },
    {
        "username": "caj_scz1",
        "email": "caj_scz1@example.com",
        "password": "Cajero123!",
        "role": "CAJE",
        "office_code": "SCZ-03",
    },
    {
        "username": "caj_scz2",
        "email": "caj_scz2@example.com",
        "password": "Cajero123!",
        "role": "CAJE",
        "office_code": "SCZ-05",
    },
    {
        "username": "caj_cbb1",
        "email": "caj_cbb1@example.com",
        "password": "Cajero123!",
        "role": "CAJE",
        "office_code": "CBB-03",
    },
    {
        "username": "caj_oru1",
        "email": "caj_oru1@example.com",
        "password": "Cajero123!",
        "role": "CAJE",
        "office_code": "ORU-02",
    },
    {
        "username": "caj_pts1",
        "email": "caj_pts1@example.com",
        "password": "Cajero123!",
        "role": "CAJE",
        "office_code": "PTS-02",
    },
    {
        "username": "caj_trj1",
        "email": "caj_trj1@example.com",
        "password": "Cajero123!",
        "role": "CAJE",
        "office_code": "TRJ-02",
    },
]


class Command(BaseCommand):
    help = "Crea usuarios iniciales de prueba en distintas oficinas y roles"

    def handle(self, *args, **options):
        for data in SEED_USERS:
            office = None
            if data.get("office_code"):
                try:
                    office = Office.objects.get(code=data["office_code"])
                except Office.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(f"⚠ Oficina {data['office_code']} no encontrada, usuario {data['username']} sin office")
                    )

            user, created = User.objects.get_or_create(
                username=data["username"],
                defaults={
                    "email": data["email"],
                    "role": data["role"],
                    "office": office,
                },
            )
            if created:
                user.set_password(data["password"])
                user.save()
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Usuario creado: {user.username} ({user.role}, {office.code if office else 'sin office'})")
                )
            else:
                self.stdout.write(f"• Usuario ya existía: {user.username}")

        self.stdout.write(self.style.SUCCESS("Usuarios de prueba listos ✅"))
