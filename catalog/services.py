# apps/catalog/services.py
from __future__ import annotations
from typing import List, Dict, Optional
from django.db import transaction
from django.db.models import Max

from .models import Bus, Seat


class SeatsAlreadyExist(Exception):
    """Error custom: usado si el bus ya tiene asientos y el modo es 'fail_if_exists'."""
    pass


def create_default_seats_for_bus(
    bus: Bus,
    *,
    mode: str = "fail_if_exists",  # opciones: "fail_if_exists" | "replace" | "append"
    deck: int = 1,
    kind: str = Seat.KIND_NORMAL,
) -> int:
    """
    Genera asientos simples 1..capacity en un único piso (deck) con mismo tipo (kind).

    - Útil como "bootstrap" rápido: creas un bus y automáticamente se llenan los asientos.
    - Internamente delega a create_seats_from_blocks() con un solo bloque.

    Args:
        bus: instancia persistida de Bus.
        mode: cómo actuar si ya existen asientos.
        deck: piso por defecto (1).
        kind: tipo por defecto (NORMAL).

    Returns:
        int: cantidad de asientos creados.
    """
    return create_seats_from_blocks(
        bus,
        blocks=[{"deck": deck, "kind": kind, "count": bus.capacity or 0}],
        mode=mode,
    )


def create_seats_from_blocks(
    bus: Bus,
    blocks: List[Dict],
    *,
    mode: str = "fail_if_exists",  # opciones: "fail_if_exists" | "replace" | "append"
    start_number: Optional[int] = None,
) -> int:
    """
    Genera asientos a partir de BLOQUES declarativos. Cada bloque define cómo se crean.

    Formato esperado de cada bloque:
      {
        "deck": 1 | 2,                  # piso
        "kind": Seat.KIND_*,            # tipo de asiento
        "count": int,                   # cuántos asientos generar
        "row": None | int,              # fila (opcional, si usas grilla)
        "col": None | int,              # columna (opcional, si usas grilla)
        "start_number": Optional[int],  # nro inicial para ese bloque
      }

    - "replace": elimina los asientos existentes del bus y crea nuevos desde cero.
    - "append": añade asientos después del último número existente.
    - "fail_if_exists": lanza SeatsAlreadyExist si ya hay asientos en ese bus.

    La lógica está protegida con transaction.atomic() → garantiza atomicidad:
    si ocurre un error, ningún asiento se persiste en DB.

    Returns:
        int: cantidad de asientos creados.
    """
    if not isinstance(blocks, list) or not blocks:
        return 0

    with transaction.atomic():  # ← control de transacciones
        existing_qs = bus.seats.all()

        # Validación según modo elegido
        if mode == "fail_if_exists" and existing_qs.exists():
            raise SeatsAlreadyExist(f"El bus {bus.code} ya tiene asientos.")

        if mode == "replace":
            existing_qs.delete()

        # Determinar desde qué número comenzar
        if start_number is not None:
            next_number = int(start_number)
        else:
            max_num = existing_qs.aggregate(m=Max("number"))["m"] or 0
            next_number = max_num + 1

        bulk = []
        current_number = next_number

        # Iterar sobre bloques declarativos
        for blk in blocks:
            deck = int(blk.get("deck", 1))
            kind = blk.get("kind", Seat.KIND_NORMAL)
            count = int(blk.get("count", 0))
            blk_start = blk.get("start_number")

            # Validaciones básicas
            if deck < 1 or deck > 2:
                raise ValueError("deck debe ser 1 o 2.")
            if count < 0:
                raise ValueError("count no puede ser negativo.")
            if kind not in dict(Seat.KIND_CHOICES):
                raise ValueError(f"kind inválido: {kind}")

            # Si se especificó un número inicial para el bloque, lo usamos
            if blk_start is not None:
                current_number = int(blk_start)

            # Crear cada asiento del bloque
            for i in range(count):
                row = blk.get("row")
                col = blk.get("col")
                # Si defines grilla, deben venir row y col juntos
                if (row is None) ^ (col is None):
                    raise ValueError("Si defines 'row', debes definir 'col' (y viceversa).")

                bulk.append(
                    Seat(
                        bus=bus,
                        number=current_number,
                        deck=deck,
                        row=row,
                        col=col,
                        kind=kind,
                        is_accessible=bool(blk.get("is_accessible", False)),
                        active=bool(blk.get("active", True)),
                        notes=str(blk.get("notes", ""))[:160],
                    )
                )
                current_number += 1

        if not bulk:
            return 0

        # Inserción en bulk → eficiente
        Seat.objects.bulk_create(bulk)
        return len(bulk)
