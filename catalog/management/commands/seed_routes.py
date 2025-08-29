# catalog/management/commands/seed_routes.py
from django.core.management.base import BaseCommand
from django.db import transaction
from catalog.models import Office, Route, RouteStop

# Cada ruta se define por una secuencia de códigos de Office en orden.
# El primer código es ORIGEN, el último es DESTINO; los intermedios son paradas.
ROUTE_PATHS = [
    # ---- SANTA CRUZ (4 rutas) ----
    ["SCZ-01", "SCZ-03", "SCZ-02"],  # Bimodal → Warnes → Montero
    ["SCZ-01", "SCZ-04"],  # Bimodal → La Guardia
    ["SCZ-01", "SCZ-05"],  # Bimodal → Cotoca
    ["SCZ-02", "SCZ-03", "SCZ-01"],  # Montero → Warnes → Bimodal

    # ---- COCHABAMBA (4 rutas) ----
    ["CBB-01", "CBB-06", "CBB-05", "CBB-04", "CBB-03", "CBB-02"],  # Terminal → Villa Tunari → … → Bulo Bulo
    ["CBB-02", "CBB-03", "CBB-04"],  # Bulo Bulo → Ivirgarzama → Chimoré
    ["CBB-01", "CBB-05", "CBB-06"],  # Terminal → Shinahota → Villa Tunari
    ["CBB-01", "CBB-02"],  # Terminal → Bulo Bulo (directa)

    # ---- LA PAZ (4 rutas) ----
    ["LPZ-01", "LPZ-02", "LPZ-03"],  # La Paz → El Alto → Viacha
    ["LPZ-01", "LPZ-04"],  # La Paz → Patacamaya
    ["LPZ-02", "LPZ-01"],  # El Alto → La Paz
    ["LPZ-03", "LPZ-01", "LPZ-04"],  # Viacha → La Paz → Patacamaya

    # ---- ORURO (4 rutas) ----
    ["ORU-01", "ORU-02"],  # Oruro → Caracollo
    ["ORU-01", "ORU-03"],  # Oruro → Huanuni
    ["ORU-01", "ORU-04"],  # Oruro → Challapata
    ["ORU-02", "ORU-01", "ORU-03"],  # Caracollo → Oruro → Huanuni

    # ---- POTOSÍ (4 rutas) ----
    ["PTS-01", "PTS-02"],  # Potosí → Uyuni
    ["PTS-01", "PTS-03"],  # Potosí → Tupiza
    ["PTS-03", "PTS-04"],  # Tupiza → Villazón
    ["PTS-01", "PTS-03", "PTS-04"],  # Potosí → Tupiza → Villazón

    # ---- TARIJA (4 rutas) ----
    ["TRJ-01", "TRJ-02"],  # Tarija → Yacuiba
    ["TRJ-01", "TRJ-03"],  # Tarija → Bermejo
    ["TRJ-02", "TRJ-01", "TRJ-03"],  # Yacuiba → Tarija → Bermejo
    ["TRJ-03", "TRJ-01"],  # Bermejo → Tarija
]

BASE_MIN_PER_TRAMO = 60  # offset por tramo en minutos (0 origen, 60 primera parada, etc.)


def _fetch_offices_by_codes(codes):
    """Devuelve una lista de Office en el mismo orden que codes; si falta alguna, retorna None."""
    offices = []
    missing = []
    code_to_off = {o.code: o for o in Office.objects.filter(code__in=codes)}
    for c in codes:
        off = code_to_off.get(c)
        if not off:
            missing.append(c)
        offices.append(off)
    if missing:
        return None, missing
    return offices, []


def _route_name_from_codes(codes):
    if len(codes) <= 2:
        return f"{codes[0]} → {codes[-1]}"
    middle = ", ".join(codes[1:-1])
    # Limitar a 120 caracteres por el max_length del modelo
    name = f"{codes[0]} → {codes[-1]} (via {middle})"
    return name[:120]


class Command(BaseCommand):
    help = "Crea rutas (Route) y sus paradas (RouteStop) a partir de códigos de oficinas"

    @transaction.atomic
    def handle(self, *args, **options):
        routes_created = 0
        stops_created = 0
        skipped = 0

        for path in ROUTE_PATHS:
            if len(path) < 2:
                self.stdout.write(self.style.WARNING(f"⚠ Ruta inválida (se requieren ≥ 2 códigos): {path}"))
                skipped += 1
                continue

            offices, missing = _fetch_offices_by_codes(path)
            if missing:
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠ Omitiendo ruta {path}: oficinas no encontradas: {', '.join(missing)}"
                    )
                )
                skipped += 1
                continue

            name = _route_name_from_codes(path)
            origin = offices[0]
            destination = offices[-1]

            route, created = Route.objects.get_or_create(
                name=name,
                defaults={
                    "origin": origin,
                    "destination": destination,
                    "active": True,
                },
            )

            if created:
                routes_created += 1
                self.stdout.write(self.style.SUCCESS(f"✓ Ruta creada: {route.name}"))

                # Crear paradas en orden
                for idx, off in enumerate(offices):
                    stop, s_created = RouteStop.objects.get_or_create(
                        route=route,
                        order=idx,
                        defaults={
                            "office": off,
                            "scheduled_offset_min": idx * BASE_MIN_PER_TRAMO,
                        },
                    )
                    if s_created:
                        stops_created += 1
                    else:
                        # Si ya existe por order, asegurar que apunte a la office esperada
                        if stop.office_id != off.id:
                            stop.office = off
                            stop.scheduled_offset_min = idx * BASE_MIN_PER_TRAMO
                            stop.save(update_fields=["office", "scheduled_offset_min"])

                self.stdout.write(
                    self.style.SUCCESS(
                        f"    • Paradas creadas/actualizadas: {len(offices)}"
                    )
                )
            else:
                self.stdout.write(f"• Ruta ya existía: {route.name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Rutas listas ✅ (nuevas: {routes_created}, paradas nuevas: {stops_created}, omitidas: {skipped})"
            )
        )
