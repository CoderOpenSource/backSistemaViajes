from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()

SEED_USERS = [
    {
        "username": "admin",
        "email": "admin@example.com",
        "password": "Admin123!",
        "role": "ADMIN",
    },
    {
        "username": "vendedor",
        "email": "vendedor@example.com",
        "password": "Vendedor123!",
        "role": "VEND",
    },
    {
        "username": "cajero",
        "email": "cajero@example.com",
        "password": "Cajero123!",
        "role": "CAJE",
    },
]


class Command(BaseCommand):
    help = "Crea usuarios iniciales para cada rol"

    def handle(self, *args, **options):
        for data in SEED_USERS:
            user, created = User.objects.get_or_create(
                username=data["username"],
                defaults={
                    "email": data["email"],
                    "role": data["role"],
                },
            )
            if created:
                user.set_password(data["password"])
                user.save()
                self.stdout.write(self.style.SUCCESS(f"✓ Usuario creado: {user.username} ({user.role})"))
            else:
                self.stdout.write(f"• Usuario ya existía: {user.username}")

        self.stdout.write(self.style.SUCCESS("Usuarios iniciales listos ✅"))
