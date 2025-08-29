# apps/ventas/serializers.py
from __future__ import annotations
from decimal import Decimal
from typing import Optional

from rest_framework import serializers
from django.utils import timezone

from .models import Ticket, Payment, PaymentMethod, Refund, Receipt
from passenger.models import Passenger
from catalog.models import Departure, Seat, Office

from . import services  # ← usamos las funciones con transacciones/locks


# ===========================
# Helpers de lectura anidada
# ===========================
def _office_min(office: Office):
    return {"id": str(office.id), "code": office.code, "name": office.name}


# ===========================
# TICKETS
# ===========================
class TicketReadSerializer(serializers.ModelSerializer):
    passenger = serializers.SerializerMethodField()
    departure = serializers.SerializerMethodField()
    seat = serializers.SerializerMethodField()
    origin = serializers.SerializerMethodField()
    destination = serializers.SerializerMethodField()
    office_sold = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id", "status", "price",
            "paid_at", "created_at",
            "passenger", "departure", "seat",
            "origin", "destination",
            "office_sold", "seller",
        ]

    def get_passenger(self, obj: Ticket):
        p: Passenger = obj.passenger
        full_name = getattr(p, "full_name", None) or f"{getattr(p, 'first_name', '')} {getattr(p, 'last_name', '')}".strip()
        return {
            "id": str(p.id),
            "document": getattr(p, "document", None) or getattr(p, "nro_doc", None),
            "full_name": full_name,
        }

    def get_departure(self, obj: Ticket):
        d: Departure = obj.departure
        return {
            "id": str(d.id),
            "route": getattr(d.route, "name", None) if getattr(d, "route", None) else None,
            "bus": getattr(d.bus, "plate", None) if getattr(d, "bus", None) else None,
            "scheduled_at": getattr(d, "scheduled_departure_at", None),
        }

    def get_seat(self, obj: Ticket):
        s: Seat = obj.seat
        return {"id": str(s.id), "number": s.number, "deck": getattr(s, "deck", None)}

    def get_origin(self, obj: Ticket):
        return _office_min(obj.origin)

    def get_destination(self, obj: Ticket):
        return _office_min(obj.destination)

    def get_office_sold(self, obj: Ticket):
        return _office_min(obj.office_sold)

    def get_seller(self, obj: Ticket):
        u = obj.seller
        return {"id": u.id, "username": u.get_username(), "full_name": getattr(u, "get_full_name", lambda: "")()}


class TicketWriteSerializer(serializers.ModelSerializer):
    passenger = serializers.PrimaryKeyRelatedField(queryset=Passenger.objects.all())
    departure = serializers.PrimaryKeyRelatedField(queryset=Departure.objects.all())
    seat = serializers.PrimaryKeyRelatedField(queryset=Seat.objects.all())
    origin = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all())
    destination = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all())
    office_sold = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all())

    class Meta:
        model = Ticket
        fields = [
            "id",
            "passenger", "departure", "seat",
            "origin", "destination",
            "office_sold", "seller",
            "status", "price", "paid_at",
        ]
        read_only_fields = ["id", "paid_at"]

    def validate(self, data):
        # Validaciones de integridad previa (rápidas); la verificación final ocurre en services.create_ticket_safe
        departure = data.get("departure") or getattr(self.instance, "departure", None)
        seat = data.get("seat") or getattr(self.instance, "seat", None)
        origin = data.get("origin") or getattr(self.instance, "origin", None)
        destination = data.get("destination") or getattr(self.instance, "destination", None)

        if departure and seat and departure.bus_id != seat.bus_id:
            raise serializers.ValidationError("El asiento seleccionado no pertenece al bus de esta salida.")

        if departure and origin and destination:
            route = departure.route
            stops = {rs.office_id: rs.order for rs in route.stops.all()}
            if origin.id not in stops or destination.id not in stops:
                raise serializers.ValidationError("Origen y/o destino no pertenecen a la ruta de la salida.")
            if stops[origin.id] >= stops[destination.id]:
                raise serializers.ValidationError("El origen debe ser anterior al destino en la ruta.")
        return data

    def create(self, validated_data):
        request = self.context.get("request")
        if request and not validated_data.get("seller"):
            validated_data["seller"] = request.user

        ticket = services.create_ticket_safe(
            passenger=validated_data["passenger"],
            departure_id=validated_data["departure"].id,
            seat_id=validated_data["seat"].id,
            origin_id=validated_data["origin"].id,
            destination_id=validated_data["destination"].id,
            office_sold_id=validated_data["office_sold"].id,
            seller=validated_data["seller"],
            price=validated_data["price"],
            initial_status=validated_data.get("status", Ticket.STATUS_RESERVED),
        )
        return ticket

    def update(self, instance, validated_data):
        # Mantén updates simples (ej. notas/estado). No re-asignes asiento o trayecto en producción.
        new_status = validated_data.get("status", instance.status)
        if new_status == Ticket.STATUS_PAID and not instance.paid_at and not validated_data.get("paid_at"):
            validated_data["paid_at"] = timezone.now()
        return super().update(instance, validated_data)


# ===========================
# PAYMENT METHODS
# ===========================
class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = ["id", "code", "name", "active", "notes"]


# ===========================
# PAYMENTS
# ===========================
class PaymentReadSerializer(serializers.ModelSerializer):
    ticket = serializers.PrimaryKeyRelatedField(read_only=True)
    method = PaymentMethodSerializer(read_only=True)
    office = serializers.SerializerMethodField()
    cashier = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id", "ticket", "method", "amount", "currency",
            "transaction_id", "status", "office", "cashier",
            "paid_at", "created_at",
        ]

    def get_office(self, obj: Payment):
        return _office_min(obj.office) if obj.office else None

    def get_cashier(self, obj: Payment):
        u = obj.cashier
        if not u:
            return None
        return {"id": u.id, "username": u.get_username(), "full_name": getattr(u, "get_full_name", lambda: "")()}


class PaymentCreateSerializer(serializers.Serializer):
    ticket = serializers.PrimaryKeyRelatedField(queryset=Ticket.objects.all())
    method = serializers.PrimaryKeyRelatedField(queryset=PaymentMethod.objects.all())
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    currency = serializers.CharField(max_length=8, default="BOB")
    office = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all(), required=False, allow_null=True)
    transaction_id = serializers.CharField(max_length=80, required=False, allow_blank=True)
    confirm = serializers.BooleanField(default=False)

    def create(self, validated_data):
        request = self.context.get("request")
        cashier = getattr(request, "user", None) if request else None

        payment = services.record_payment_safe(
            ticket_id=validated_data["ticket"].id,
            method_id=validated_data["method"].id,
            amount=validated_data["amount"],
            currency=validated_data.get("currency", "BOB"),
            cashier=cashier,
            office_id=validated_data.get("office").id if validated_data.get("office") else None,
            transaction_id=validated_data.get("transaction_id") or None,
            confirm=validated_data.get("confirm", False),
        )
        return payment


class PaymentConfirmSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField()

    def create(self, validated_data):
        payment = services.confirm_payment_safe(payment_id=str(validated_data["payment_id"]))
        return payment


# ===========================
# REFUNDS
# ===========================
class RefundReadSerializer(serializers.ModelSerializer):
    payment = serializers.PrimaryKeyRelatedField(read_only=True)
    processed_by = serializers.SerializerMethodField()
    refund_pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = Refund
        fields = [
            "id", "payment", "amount", "currency",
            "reason", "status", "processed_at", "created_at",
            "processed_by", "refund_pdf_url",
        ]

    def get_processed_by(self, obj: Refund):
        u = obj.processed_by
        if not u:
            return None
        return {"id": u.id, "username": u.get_username(), "full_name": getattr(u, "get_full_name", lambda: "")()}

    def get_refund_pdf_url(self, obj: Refund):
        try:
            return obj.refund_pdf.url if obj.refund_pdf else None
        except Exception:
            return None


class RefundCreateSerializer(serializers.Serializer):
    payment = serializers.PrimaryKeyRelatedField(queryset=Payment.objects.all())
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    reason = serializers.CharField(max_length=160, allow_blank=True, required=False)
    confirm_immediately = serializers.BooleanField(default=True)

    def create(self, validated_data):
        request = self.context.get("request")
        processed_by = getattr(request, "user", None) if request else None
        refund = services.create_refund_safe(
            payment_id=validated_data["payment"].id,
            amount=validated_data["amount"],
            reason=validated_data.get("reason", ""),
            processed_by=processed_by,
            confirm_immediately=validated_data.get("confirm_immediately", True),
        )
        return refund


# ===========================
# RECEIPTS
# ===========================
class ReceiptReadSerializer(serializers.ModelSerializer):
    payment = serializers.PrimaryKeyRelatedField(read_only=True)
    issuer_office = serializers.SerializerMethodField()
    issuer = serializers.SerializerMethodField()
    receipt_pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = [
            "id", "payment", "number", "issued_at",
            "total_amount", "currency",
            "issuer_office", "issuer", "status", "notes",
            "receipt_pdf_url",
        ]

    def get_issuer_office(self, obj: Receipt):
        return _office_min(obj.issuer_office) if obj.issuer_office else None

    def get_issuer(self, obj: Receipt):
        u = obj.issuer
        return {"id": u.id, "username": u.get_username(), "full_name": getattr(u, "get_full_name", lambda: "")()}

    def get_receipt_pdf_url(self, obj: Receipt):
        try:
            return obj.receipt_pdf.url if obj.receipt_pdf else None
        except Exception:
            return None


class ReceiptCreateSerializer(serializers.Serializer):
    payment = serializers.PrimaryKeyRelatedField(queryset=Payment.objects.all())
    number = serializers.CharField(max_length=40)
    issuer_office = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all())
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    currency = serializers.CharField(max_length=8, default="BOB")
    notes = serializers.CharField(max_length=160, allow_blank=True, required=False)

    def create(self, validated_data):
        request = self.context.get("request")
        issuer = getattr(request, "user", None) if request else None

        # Puedes pasar un callback que genere/suba el PDF post-commit desde la view (context)
        build_pdf_callback = self.context.get("build_pdf_callback")

        receipt = services.issue_receipt_safe(
            payment_id=validated_data["payment"].id,
            number=validated_data["number"],
            issuer_office_id=validated_data["issuer_office"].id,
            issuer=issuer,
            total_amount=validated_data.get("total_amount", None),
            currency=validated_data.get("currency", "BOB"),
            notes=validated_data.get("notes", ""),
            build_pdf_callback=build_pdf_callback,
        )
        return receipt
