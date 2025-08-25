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


# ---------- BUSES ----------
class BusViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    queryset = Bus.objects.all()
    serializer_class = BusSerializer
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


# ---------- ROUTES ----------
class RouteViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    queryset = Route.objects.prefetch_related("stops__office", "origin", "destination").all()
    serializer_class = RouteSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "active": ["exact"],
        "origin": ["exact"],
        "destination": ["exact"],
        "name": ["exact", "icontains"],
    }
    search_fields = ["name", "origin__name", "destination__name"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]


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
