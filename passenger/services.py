# pasajeros/services.py
import uuid
from django.db import transaction, IntegrityError
from .models import Passenger, PassengerRelation

def crear_menor_con_apoderado(data_menor: dict, data_apoderado: dict, parentesco="Tutor", es_tutor_legal=True):
    """
    Crea un menor con su apoderado y la relación entre ambos dentro de una transacción.

    ¿Por qué usar una transacción aquí?
    ----------------------------------
    El registro de un menor involucra tres pasos dependientes:
      1. Crear el pasajero menor.
      2. Crear o reutilizar el apoderado.
      3. Crear la relación entre menor y apoderado.

    Si alguno de estos pasos falla (ejemplo: error de integridad,
    duplicado, fallo de concurrencia, etc.), necesitamos que
    *ningún cambio* quede persistido en la base de datos.
    De lo contrario, podríamos terminar con un menor creado
    sin apoderado, o con relaciones huérfanas.

    Usar `transaction.atomic()` garantiza que los tres pasos
    ocurran de forma atómica: o se ejecutan todos, o no se ejecuta ninguno.

    Args:
        data_menor (dict): Datos para crear el Passenger menor.
        data_apoderado (dict): Datos para crear/reusar el Passenger apoderado.
        parentesco (str): Tipo de parentesco (ej: "Padre", "Madre", "Tutor").
        es_tutor_legal (bool): Marca si el apoderado es tutor legal.

    Returns:
        Passenger: El pasajero menor creado (con relación a su apoderado).

    Raises:
        Exception: Si ocurre un error de integridad, se lanza para que
                   la view o el caller manejen la respuesta adecuada.
    """
    try:
        with transaction.atomic():
            # Crear menor
            menor = Passenger.objects.create(**data_menor)

            # Crear apoderado (o reusar si ya existe)
            apoderado, created = Passenger.objects.get_or_create(
                tipo_doc=data_apoderado["tipo_doc"],
                nro_doc=data_apoderado["nro_doc"],
                defaults=data_apoderado,
            )

            # Crear relación
            PassengerRelation.objects.create(
                menor=menor,
                apoderado=apoderado,
                parentesco=parentesco,
                es_tutor_legal=es_tutor_legal,
            )

            return menor

    except IntegrityError as e:
        # Manejo de errores de concurrencia o duplicados
        raise Exception(f"Error creando menor y apoderado: {str(e)}")
