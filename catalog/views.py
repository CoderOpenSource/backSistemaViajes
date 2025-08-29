# apps/catalog/views.py
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from accounts.permissions import IsAdmin  # tu permiso admin

from .models import (
    Office, Bus, Route, Departure,
    CrewMember, DriverLicense, DepartureAssignment
)
from .serializers import (
    OfficeSerializer, BusSerializer, RouteSerializer, DepartureSerializer,
    CrewMemberSerializer, DriverLicenseSerializer, DepartureAssignmentSerializer,
    DepartureWithCrewSerializer, SimpleCrewMemberReadSerializer
)


# Helper: lecturas para autenticados, escrituras solo admin
class AdminWriteAuthenticatedReadMixin:
    permission_classes = [permissions.IsAuthenticated]  # default

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        return [IsAdmin()]


# ---------- OFFICES ----------
class OfficeViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    queryset = Office.objects.all()
    serializer_class = OfficeSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "active": ["exact"],
        "code": ["exact", "icontains"],
        "department": ["exact", "icontains"],
        "province": ["exact", "icontains"],
        "municipality": ["exact", "icontains"],
        "locality": ["exact", "icontains"],
    }
    search_fields = ["name", "address", "phone", "code", "department", "province", "municipality", "locality"]
    ordering_fields = ["code", "department", "province", "municipality", "locality", "name", "created_at"]
    ordering = ["code"]

# apps/catalog/viewsets.py
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import Bus, Seat
from .serializers import BusSerializer, SeatBlockSerializer
from .services import create_seats_from_blocks

# ---------- BUSES ----------
from django.db.models import Count
from django.utils.decorators import method_decorator

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import Bus, Seat
from .serializers import BusSerializer, SeatBlockSerializer
from .services import create_seats_from_blocks  # ajusta el import si tu helper vive en otro módulo


class BusViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    """
    - Soporta seat_blocks vía BusSerializer al crear/editar.
    - Acciones extra:
        * GET   /buses/{id}/seats/            -> listar asientos
        * GET   /buses/{id}/seat-blocks/      -> bloques actuales (reconstruidos)
        * POST  /buses/{id}/seats/regenerate/ -> reemplazar asientos con seat_blocks
    """
    queryset = (
        Bus.objects
        .all()
        .prefetch_related("seats")          # ✅ evita N+1 en serializer y acciones
        .order_by("code")
        .annotate(_seats_count=Count("seats"))  # opcional para listas
    )
    serializer_class = BusSerializer
    permission_classes = [IsAuthenticated]  # AdminWriteAuthenticatedReadMixin ya limita escritura a admin

    # Filtros/orden
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "active": ["exact"],
        "year": ["exact", "gte", "lte"],
        "plate": ["exact", "icontains"],
        "code": ["exact", "icontains"],
    }
    search_fields = ["code", "model", "plate", "chassis_number"]
    ordering_fields = ["code", "year", "plate", "created_at"]
    ordering = ["code"]

    # ------- Acciones auxiliares --------

    @action(detail=True, methods=["get"], url_path="seats")
    def list_seats(self, request, pk=None):
        """
        Devuelve los asientos del bus:
        [{id, number, deck, row, col, kind, is_accessible, active}, ...]
        """
        bus = self.get_object()
        seats = (
            Seat.objects
            .filter(bus=bus)
            .order_by("deck", "number")
            .values("id", "number", "deck", "row", "col", "kind", "is_accessible", "active")
        )
        return Response(list(seats), status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="seat-blocks")
    def seat_blocks(self, request, pk=None):
        """
        Devuelve los bloques actuales reconstruidos desde los asientos:
        [{deck, kind, count, start_number}, ...]
        Útil para precargar el modal de edición.
        """
        bus = self.get_object()

        # Mismo algoritmo que el SerializerMethodField `seat_blocks_current`
        qs = (
            bus.seats
            .all()
            .order_by("deck", "kind", "number")
            .values("deck", "kind", "number")
        )

        blocks = []
        last = None  # [deck, kind, prev_num, start, count]
        for s in qs:
            dk = (s["deck"], s["kind"])
            num = s["number"]
            if last is None:
                last = [dk[0], dk[1], num, num, 1]
                continue

            same_group = (last[0] == dk[0] and last[1] == dk[1] and num == last[2] + 1)
            if same_group:
                last[2] = num
                last[4] += 1
            else:
                blocks.append({
                    "deck": last[0],
                    "kind": last[1],
                    "count": last[4],
                    "start_number": last[3],
                })
                last = [dk[0], dk[1], num, num, 1]

        if last is not None:
            blocks.append({
                "deck": last[0],
                "kind": last[1],
                "count": last[4],
                "start_number": last[3],
            })

        return Response(blocks, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="seats/regenerate")
    def regenerate_seats(self, request, pk=None):
        """
        Reemplaza TODOS los asientos del bus con los bloques enviados.

        Body:
        {
          "seat_blocks": [
            {"deck":1, "kind":"SEMI_CAMA", "count":24, "start_number":1},
            {"deck":2, "kind":"CAMA", "count":20, "start_number":25}
          ]
        }
        """
        bus = self.get_object()
        data = request.data or {}
        blocks = data.get("seat_blocks", [])

        # Validar formato de bloques
        serializer = SeatBlockSerializer(data=blocks, many=True)
        serializer.is_valid(raise_exception=True)

        # Validar coherencia con la capacidad
        total = sum(int(b.get("count", 0)) for b in serializer.validated_data)
        if total != bus.capacity:
            return Response(
                {"seat_blocks": f"La suma de 'count' ({total}) debe coincidir con 'capacity' ({bus.capacity})."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reemplazar asientos
        created = create_seats_from_blocks(bus, serializer.validated_data, mode="replace")
        return Response(
            {"message": f"Asientos regenerados: {created} creados.", "created": created},
            status=status.HTTP_200_OK,
        )


# ---------- ROUTES ----------

class RouteViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    queryset = (
        Route.objects
        .select_related("origin", "destination")
        .prefetch_related("stops__office")
        .all()
    )
    serializer_class = RouteSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "active": ["exact"],
        "origin": ["exact"],
        "destination": ["exact"],
        "name": ["exact", "icontains"],
    }
    search_fields = ["name", "origin__name", "destination__name", "origin__code", "destination__code"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    @action(detail=True, methods=["patch"], url_path="reorder-stops")
    def reorder_stops(self, request, pk=None):
        """
        Reordena las paradas manteniendo origen en 0 y destino al final.
        Body: { "stop_ids": [ <ids de RouteStop en el nuevo orden> ] }
        """
        route = self.get_object()
        stop_ids = request.data.get("stop_ids")
        if not isinstance(stop_ids, list) or not stop_ids:
            return Response({"detail": "stop_ids requerido (lista)."}, status=status.HTTP_400_BAD_REQUEST)

        # Paradas actuales
        stops = list(route.stops.order_by("order").only("id", "order"))
        current_ids_sorted = sorted(s.id for s in stops)
        if sorted(stop_ids) != current_ids_sorted:
            return Response({"detail": "Los IDs no coinciden con las paradas actuales."}, status=status.HTTP_400_BAD_REQUEST)

        # Origen/destino deben permanecer en extremos
        if stop_ids[0] != stops[0].id or stop_ids[-1] != stops[-1].id:
            return Response({"detail": "No puedes mover la parada de origen ni la de destino."}, status=status.HTTP_400_BAD_REQUEST)

        # aplicar nuevo order
        mapping = {sid: idx for idx, sid in enumerate(stop_ids)}
        for s in stops:
            s.order = mapping[s.id]
        RouteStop.objects.bulk_update(stops, ["order"])

        return Response(self.get_serializer(route).data, status=status.HTTP_200_OK)

# ---------- DEPARTURES ----------
class DepartureViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    queryset = Departure.objects.select_related(
        "route", "bus", "driver", "route__origin", "route__destination"
    ).all()
    serializer_class = DepartureSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "status": ["exact"],
        "route": ["exact"],
        "bus": ["exact"],
        "driver": ["exact"],
        "scheduled_departure_at": ["date__gte", "date__lte", "gte", "lte"],
    }
    search_fields = ["route__name", "bus__code", "bus__plate", "driver__username", "notes"]
    ordering_fields = ["scheduled_departure_at", "status", "route", "bus", "created_at"]
    ordering = ["-scheduled_departure_at"]

    # ---- Alternar serializer para incluir tripulación al recuperar/listar (opcional) ----
    def get_serializer_class(self):
        # Si el cliente pide "embed_crew=true" devolvemos la versión con tripulación
        if self.action in ["list", "retrieve"] and self.request.query_params.get("embed_crew") == "true":
            return DepartureWithCrewSerializer
        return super().get_serializer_class()

    # ---- Endpoints auxiliares ----
    @action(detail=True, methods=["get"], url_path="crew", permission_classes=[permissions.IsAuthenticated])
    def crew(self, request, pk=None):
        """Devuelve choferes y ayudantes activos de la salida."""
        dep = self.get_object()
        drivers = SimpleCrewMemberReadSerializer(dep.crew_drivers, many=True).data
        assistants = SimpleCrewMemberReadSerializer(dep.crew_assistants, many=True).data
        return Response({"drivers": drivers, "assistants": assistants})

    @action(detail=True, methods=["post"], url_path="assign", permission_classes=[IsAdmin])
    def assign(self, request, pk=None):
        """
        Asigna un crew a la departure.
        body: { "crew_member": <id>, "role": "DRIVER|ASSISTANT", "slot": 1|2, "notes": "..." }
        """
        dep = self.get_object()
        data = {
            "departure": dep.id,
            "crew_member": request.data.get("crew_member"),
            "role": request.data.get("role"),
            "slot": request.data.get("slot"),
            "notes": request.data.get("notes", ""),
        }
        ser = DepartureAssignmentSerializer(data=data)
        ser.is_valid(raise_exception=True)
        assignment = ser.save()
        return Response(DepartureAssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="unassign", permission_classes=[IsAdmin])
    def unassign(self, request, pk=None):
        """
        Desasigna un crew de la departure.
        Acepta:
          - assignment_id   (preferido)  ó
          - crew_member + role (+ slot opcional) para ubicar la asignación activa.
        """
        dep = self.get_object()
        assignment_id = request.data.get("assignment_id")
        qs = DepartureAssignment.objects.filter(departure=dep, unassigned_at__isnull=True)

        if assignment_id:
            assign = qs.filter(id=assignment_id).first()
        else:
            crew_member = request.data.get("crew_member")
            role = request.data.get("role")
            slot = request.data.get("slot")
            if not (crew_member and role):
                return Response({"detail": "Se requiere 'assignment_id' o ('crew_member' y 'role')."},
                                status=status.HTTP_400_BAD_REQUEST)
            qs = qs.filter(crew_member_id=crew_member, role=role)
            if slot:
                qs = qs.filter(slot=slot)
            assign = qs.first()

        if not assign:
            return Response({"detail": "Asignación activa no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        assign.unassigned_at = timezone.now()
        assign.save(update_fields=["unassigned_at"])
        return Response({"detail": "Desasignado.", "assignment": DepartureAssignmentSerializer(assign).data})

# ======================================================
#           VISTAS DE TRIPULACIÓN Y LICENCIAS
# ======================================================

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework import viewsets, permissions
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser

from accounts.permissions import IsAdmin
from .models import CrewMember, DriverLicense, DepartureAssignment
from .serializers import (
    CrewMemberSerializer,
    DriverLicenseSerializer,
    DepartureAssignmentSerializer,
)

# Helper: lecturas para autenticados, escrituras solo admin
class AdminWriteAuthenticatedReadMixin:
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        return [IsAdmin()]

# ---------- CREW MEMBERS ----------
class CrewMemberViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    # 👇 traer la oficina en la misma query
    queryset = CrewMember.objects.select_related("office").all()
    serializer_class = CrewMemberSerializer

    # Ahora acepta JSON (sin foto) y multipart/form-data (con foto)
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "active": ["exact"],
        "role": ["exact"],
        "office": ["exact"],                  # 👈 filtrar por id de Office (p.ej. ?office=3)
        "code": ["exact", "icontains"],
        "national_id": ["exact", "icontains"],
        # (opcionales si quieres filtros directos por campos de Office)
        # "office__code": ["exact", "icontains"],
        # "office__name": ["exact", "icontains"],
    }
    search_fields = [
        "code", "first_name", "last_name", "national_id", "phone",
        "office__code", "office__name",     # 👈 búsqueda por oficina
    ]
    ordering_fields = [
        "code", "first_name", "last_name", "role", "created_at",
        "office__code", "office__name",     # 👈 ordenar por oficina
    ]
    ordering = ["code"]



# ---------- DRIVER LICENSES ----------
class DriverLicenseViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    queryset = DriverLicense.objects.select_related("crew_member").all()
    serializer_class = DriverLicenseSerializer
    # Acepta JSON (solo metadatos) y multipart (frente/dorso)
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "crew_member": ["exact"],
        "crew_member__role": ["exact"],        # 👈 opcional: listar licencias solo de DRIVERS
        "number": ["exact", "icontains"],
        "active": ["exact"],
        "expires_at": ["exact", "gte", "lte"],
        "issued_at": ["exact", "gte", "lte"],
    }
    search_fields = [
        "number", "category",
        "crew_member__code", "crew_member__first_name", "crew_member__last_name"
    ]
    ordering_fields = ["expires_at", "issued_at", "number", "active", "id"]
    ordering = ["-active", "expires_at"]


# ---------- DEPARTURE ASSIGNMENTS ----------
class DepartureAssignmentViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    queryset = (
        DepartureAssignment.objects
        .select_related("departure", "crew_member", "departure__route", "departure__bus")
        .all()
    )
    serializer_class = DepartureAssignmentSerializer
    parser_classes = [JSONParser, FormParser, MultiPartParser]  # por consistencia

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "departure": ["exact"],
        "crew_member": ["exact"],
        "role": ["exact"],
        "slot": ["exact"],
        "unassigned_at": ["isnull"],           # ?unassigned_at__isnull=true para activos
    }
    search_fields = [
        "departure__route__name",
        "crew_member__code", "crew_member__first_name", "crew_member__last_name"
    ]
    ordering_fields = ["departure", "role", "slot", "assigned_at"]
    ordering = ["departure", "role", "slot"]
