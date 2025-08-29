# apps/ventas/views.py
from django.utils import timezone
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, status
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import IsAdmin  # mismo patrón que catalog

from .models import Ticket
from .serializers import TicketReadSerializer, TicketWriteSerializer


# Lectura autenticados, escritura solo admin (igual que catalog)
class AdminWriteAuthenticatedReadMixin:
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        return [IsAdmin()]


class TicketViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    """
    - GET    /api/ventas/tickets/
    - POST   /api/ventas/tickets/
    - GET    /api/ventas/tickets/{id}/
    - PUT    /api/ventas/tickets/{id}/
    - PATCH  /api/ventas/tickets/{id}/
    - DELETE /api/ventas/tickets/{id}/            (si lo permites)
    - POST   /api/ventas/tickets/{id}/pay/
    - POST   /api/ventas/tickets/{id}/cancel/
    - POST   /api/ventas/tickets/{id}/no_show/
    """
    queryset = (
        Ticket.objects.select_related(
            "passenger",
            "departure", "departure__route", "departure__bus",
            "seat",
            "origin", "destination",
            "office_sold",
            "seller",
        )
        .all()
    )

    # serializer dinámico para escritura/lectura
    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return TicketWriteSerializer
        return TicketReadSerializer

    # ====== Filtros / búsqueda / orden ======
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]

    # filtros exactos y por rango si te sirven
    filterset_fields = {
        "status": ["exact"],
        "departure": ["exact"],
        "seat": ["exact"],
        "origin": ["exact"],
        "destination": ["exact"],
        "office_sold": ["exact"],
        "seller": ["exact"],
        "created_at": ["date__gte", "date__lte", "gte", "lte"],
        "paid_at": ["isnull", "date__gte", "date__lte", "gte", "lte"],
        "price": ["gte", "lte", "exact"],
    }

    # búsqueda por pasajero/doc (ajusta a tus campos reales de Passenger)
    search_fields = [
        "passenger__nombres",
        "passenger__apellidos",
        "passenger__nro_doc",
        "origin__name", "destination__name",
        "departure__route__name",
    ]

    ordering_fields = [
        "created_at", "paid_at", "price", "status",
        "departure", "origin", "destination",
    ]
    ordering = ["-created_at"]

    # ====== Acciones de negocio ======
    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        ticket = self.get_object()
        if ticket.status == Ticket.STATUS_CANCELLED:
            return Response({"detail": "No se puede pagar un ticket anulado."}, status=400)
        if ticket.status == Ticket.STATUS_PAID:
            return Response({"detail": "El ticket ya está pagado."}, status=400)
        ticket.status = Ticket.STATUS_PAID
        ticket.paid_at = timezone.now()
        ticket.full_clean()
        ticket.save(update_fields=["status", "paid_at"])
        return Response(TicketReadSerializer(ticket).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        ticket = self.get_object()
        if ticket.status == Ticket.STATUS_CANCELLED:
            return Response({"detail": "El ticket ya está anulado."}, status=400)
        ticket.status = Ticket.STATUS_CANCELLED
        ticket.full_clean()
        ticket.save(update_fields=["status"])
        return Response(TicketReadSerializer(ticket).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="no_show")
    def no_show(self, request, pk=None):
        ticket = self.get_object()
        ticket.status = Ticket.STATUS_NO_SHOW
        ticket.full_clean()
        ticket.save(update_fields=["status"])
        return Response(TicketReadSerializer(ticket).data, status=status.HTTP_200_OK)
