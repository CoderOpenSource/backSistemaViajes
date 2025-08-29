# apps/ventas/views.py
from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, status
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import IsAdmin  # tu permiso de admin

from .models import Ticket, Payment, PaymentMethod, Refund, Receipt
from .serializers import (
    # Tickets
    TicketReadSerializer, TicketWriteSerializer,
    # Payments
    PaymentReadSerializer, PaymentCreateSerializer, PaymentConfirmSerializer,
    PaymentMethodSerializer,
    # Refunds
    RefundReadSerializer, RefundCreateSerializer,
    # Receipts
    ReceiptReadSerializer, ReceiptCreateSerializer,
)
from . import services  # acciones con transacciones y locks


# =========================
# Permisos base
# =========================
class AdminWriteAuthenticatedReadMixin:
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        return [IsAdmin()]


# =========================
# TICKETS
# =========================
class TicketViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    """
    Endpoints:
    - GET    /api/ventas/tickets/
    - POST   /api/ventas/tickets/            (usa create_ticket_safe en el serializer)
    - GET    /api/ventas/tickets/{id}/
    - PUT    /api/ventas/tickets/{id}/
    - PATCH  /api/ventas/tickets/{id}/
    - DELETE /api/ventas/tickets/{id}/       (si lo permites)
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
        ).all()
    )

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return TicketWriteSerializer
        return TicketReadSerializer

    # ====== Filtros / búsqueda / orden ======
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
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
    search_fields = [
        "passenger__nombres",
        "passenger__apellidos",
        "passenger__nro_doc",
        "origin__name", "destination__name",
        "departure__route__name",
    ]
    ordering_fields = ["created_at", "paid_at", "price", "status", "departure", "origin", "destination"]
    ordering = ["-created_at"]

    # ====== Acciones de negocio con transacciones/locks (services) ======
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        ticket = services.cancel_ticket_safe(ticket_id=pk)  # 🔒 atomic + select_for_update
        return Response(TicketReadSerializer(ticket).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="no_show")
    def no_show(self, request, pk=None):
        ticket = services.mark_no_show_safe(ticket_id=pk)  # 🔒 atomic + select_for_update
        return Response(TicketReadSerializer(ticket).data, status=status.HTTP_200_OK)

    # (Opcional) deprecado: pagos se gestionan en PaymentViewSet
    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        return Response(
            {"detail": "Endpoint deprecado. Use /api/ventas/payments/ para registrar/confirmar pagos."},
            status=status.HTTP_410_GONE,
        )


# =========================
# PAYMENT METHODS
# =========================
class PaymentMethodViewSet(AdminWriteAuthenticatedReadMixin, viewsets.ModelViewSet):
    """
    - GET    /api/ventas/payment-methods/
    - POST   /api/ventas/payment-methods/
    - GET    /api/ventas/payment-methods/{id}/
    - PUT    /api/ventas/payment-methods/{id}/
    - PATCH  /api/ventas/payment-methods/{id}/
    - DELETE /api/ventas/payment-methods/{id}/
    """
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer

    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name"]
    ordering = ["code"]


# =========================
# PAYMENTS
# =========================
class PaymentViewSet(AdminWriteAuthenticatedReadMixin, viewsets.GenericViewSet):
    """
    - GET    /api/ventas/payments/
    - GET    /api/ventas/payments/{id}/
    - POST   /api/ventas/payments/           (crear pago; puede confirmar si confirm=True)
    - POST   /api/ventas/payments/confirm/   (confirmar pago existente)
    """
    queryset = (
        Payment.objects
        .select_related("ticket", "method", "office", "cashier")
        .all()
    )
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "status": ["exact"],
        "method": ["exact"],
        "ticket": ["exact"],
        "created_at": ["date__gte", "date__lte", "gte", "lte"],
    }
    search_fields = ["transaction_id"]
    ordering_fields = ["created_at", "amount", "status"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action in ["create"]:
            return PaymentCreateSerializer
        return PaymentReadSerializer

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        return Response(PaymentReadSerializer(qs, many=True).data)

    def retrieve(self, request, pk=None):
        obj = self.get_queryset().get(pk=pk)
        return Response(PaymentReadSerializer(obj).data)

    def create(self, request):
        ser = PaymentCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        obj = ser.save()
        return Response(PaymentReadSerializer(obj).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def confirm(self, request):
        ser = PaymentConfirmSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        obj = ser.save()
        return Response(PaymentReadSerializer(obj).data, status=status.HTTP_200_OK)


# =========================
# REFUNDS
# =========================
class RefundViewSet(AdminWriteAuthenticatedReadMixin, viewsets.GenericViewSet):
    """
    - GET    /api/ventas/refunds/
    - GET    /api/ventas/refunds/{id}/
    - POST   /api/ventas/refunds/            (crear refund seguro)
    """
    queryset = Refund.objects.select_related("payment", "processed_by").all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "status": ["exact"],
        "payment": ["exact"],
        "created_at": ["date__gte", "date__lte", "gte", "lte"],
    }
    search_fields = ["reason"]
    ordering_fields = ["created_at", "amount", "status"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action in ["create"]:
            return RefundCreateSerializer
        return RefundReadSerializer

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        return Response(RefundReadSerializer(qs, many=True).data)

    def retrieve(self, request, pk=None):
        obj = self.get_queryset().get(pk=pk)
        return Response(RefundReadSerializer(obj).data)

    def create(self, request):
        ser = RefundCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        obj = ser.save()
        return Response(RefundReadSerializer(obj).data, status=status.HTTP_201_CREATED)


# =========================
# RECEIPTS
# =========================
class ReceiptViewSet(AdminWriteAuthenticatedReadMixin, viewsets.GenericViewSet):
    """
    - GET    /api/ventas/receipts/
    - GET    /api/ventas/receipts/{id}/
    - POST   /api/ventas/receipts/           (emitir recibo seguro)
    """
    queryset = Receipt.objects.select_related("payment", "issuer_office", "issuer").all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "status": ["exact"],
        "issuer_office": ["exact"],
        "created_at": ["date__gte", "date__lte", "gte", "lte"],
        "issued_at": ["date__gte", "date__lte", "gte", "lte"],
    }
    search_fields = ["number", "notes"]
    ordering_fields = ["issued_at", "number", "total_amount"]
    ordering = ["-issued_at"]

    def get_serializer_class(self):
        if self.action in ["create"]:
            return ReceiptCreateSerializer
        return ReceiptReadSerializer

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        return Response(ReceiptReadSerializer(qs, many=True).data)

    def retrieve(self, request, pk=None):
        obj = self.get_queryset().get(pk=pk)
        return Response(ReceiptReadSerializer(obj).data)

    def create(self, request):
        # Puedes inyectar un callback para generar/subir el PDF post-commit:
        # context={"build_pdf_callback": tu_funcion_pdf}
        ser = ReceiptCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        obj = ser.save()
        return Response(ReceiptReadSerializer(obj).data, status=status.HTTP_201_CREATED)
