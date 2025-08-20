# Centraliza qué permisos de modelo recibe cada grupo.
# Amplía este diccionario cuando agregues nuevas apps/modelos.

from django.contrib.auth import get_user_model

# Los codenames siguen el patrón Django:
#   'add_<model>', 'change_<model>', 'delete_<model>', 'view_<model>'

PERMISSIONS_BY_GROUP = {
    "Admin": {
        # 'ALL' es un atajo: este grupo recibirá todos los permisos existentes
        "ALL": True,
    },
    "Vendedor": {
        "ALL": False,
        "accounts": {
            "user": ["view_user"],          # Solo ver usuarios
            "auditlog": [],                  # Nada en bitácora desde admin
        },
        # Ejemplo futuro cuando tengas app 'tickets':
        # "tickets": {
        #     "boleto": ["add_boleto", "change_boleto", "view_boleto"],
        # }
    },
    "Cajero": {
        "ALL": False,
        "accounts": {
            "user": ["view_user"],
            "auditlog": [],
        },
        # "tickets": {
        #     "boleto": ["change_boleto", "view_boleto"],  # p.ej. para marcar pagado
        # }
    },
}

ADMIN_FLAGS = {
    "is_staff": True,
    "is_superuser": True,
}

User = get_user_model()
