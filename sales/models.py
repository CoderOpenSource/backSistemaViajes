# apps/ventas/models.py
import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

# ⬇️ Cloudinary para adjuntar PDFs generados (recibos y devoluciones)
from cloudinary.models import CloudinaryField

# ⬇️ Importa las clases del catálogo y úsalas directo
from catalog.models import Departure, Seat, Office
# (Opcional) si tu app passengers está instalada y quieres evitar la string:
from passenger.models import Passenger


# ======================================================
# Ticket (Boleto)
# ======================================================
class Ticket(models.Model):
    STATUS_RESERVED = "RESERVED"
    STATUS_PAID = "PAID"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_NO_SHOW = "NO_SHOW"

    STATUS_CHOICES = [
        (STATUS_RESERVED, "Reservado"),
        (STATUS_PAID, "Pagado"),
        (STATUS_CANCELLED, "Anulado"),
        (STATUS_NO_SHOW, "No se presentó"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    passenger = models.ForeignKey(
        Passenger, on_delete=models.PROTECT, related_name="tickets"
    )

    # ⬇️ Usando las clases importadas del catálogo (no strings "catalog.X")
    departure   = models.ForeignKey(Departure, on_delete=models.PROTECT, related_name="tickets")
    seat        = models.ForeignKey(Seat, on_delete=models.PROTECT, related_name="tickets")

    origin      = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="tickets_origin")
    destination = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="tickets_destination")

    office_sold = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="tickets_sold")

    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tickets_sold_by")

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_RESERVED)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["departure", "seat"]),
            models.Index(fields=["status"]),
            models.Index(fields=["departure", "origin", "destination"]),
        ]
        unique_together = ("departure", "seat", "origin", "destination")

    def __str__(self):
        return f"{self.passenger} • {self.seat} • {self.origin.code}->{self.destination.code}"

    # --- Agregados útiles ---
    @property
    def amount_paid(self) -> Decimal:
        """
        Suma de montos de pagos confirmados del ticket (excluyendo fallidos).
        Considera devoluciones para obtener el neto pagado.
        """
        total = (
            self.payments.filter(status__in=[Payment.STATUS_CONFIRMED, Payment.STATUS_PARTIALLY_REFUNDED, Payment.STATUS_REFUNDED])
            .aggregate(s=models.Sum("amount"))
            .get("s") or Decimal("0.00")
        )
        refunds = (
            Refund.objects.filter(payment__ticket=self, status=Refund.STATUS_CONFIRMED)
            .aggregate(s=models.Sum("amount"))
            .get("s") or Decimal("0.00")
        )
        return (total - refunds).quantize(Decimal("0.01"))

    @property
    def amount_due(self) -> Decimal:
        return (self.price - self.amount_paid).quantize(Decimal("0.01"))

    # --- Validaciones ---
    def clean(self):
        super().clean()

        # 1) El asiento debe pertenecer al bus de la salida
        if self.seat_id and self.departure_id:
            dep_bus_id = self.departure.bus_id
            seat_bus_id = self.seat.bus_id
            if dep_bus_id and seat_bus_id and dep_bus_id != seat_bus_id:
                raise ValidationError("El asiento seleccionado no pertenece al bus de esta salida.")

        # 2) Origen y destino válidos en la ruta (y orden correcto)
        if self.departure_id and self.origin_id and self.destination_id:
            route = self.departure.route
            stops = {rs.office_id: rs.order for rs in route.stops.all()}
            if self.origin_id not in stops or self.destination_id not in stops:
                raise ValidationError("Origen y/o destino no pertenecen a la ruta de la salida.")
            if stops[self.origin_id] >= stops[self.destination_id]:
                raise ValidationError("El origen debe ser anterior al destino en la ruta.")

        # 3) Asiento activo
        if self.seat_id and self.seat and not self.seat.active:
            raise ValidationError("El asiento está inactivo.")

    def save(self, *args, **kwargs):
        self.full_clean()
        # marcaje de paid_at: si queda completamente pagado y no tenía timestamp
        if self.status != self.STATUS_CANCELLED and self.amount_due == Decimal("0.00") and self.paid_at is None:
            self.status = self.STATUS_PAID
            self.paid_at = timezone.now()
        return super().save(*args, **kwargs)


# ======================================================
# PaymentMethod (Catálogo de métodos de pago)
# ======================================================
class PaymentMethod(models.Model):
    """
    Catálogo administrable de métodos de pago (cash, card, transfer, QR, etc.)
    """
    code = models.CharField(max_length=20, unique=True, db_index=True)  # ej: CASH, CARD, TRANSFER, QR
    name = models.CharField(max_length=60)
    active = models.BooleanField(default=True)
    notes = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["active"]),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


# ======================================================
# Payment (Pago)
# ======================================================
class Payment(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_FAILED = "FAILED"
    STATUS_PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    STATUS_REFUNDED = "REFUNDED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pendiente"),
        (STATUS_CONFIRMED, "Confirmado"),
        (STATUS_FAILED, "Fallido"),
        (STATUS_PARTIALLY_REFUNDED, "Parcialmente devuelto"),
        (STATUS_REFUNDED, "Devuelto"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="payments")
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="payments")

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default="BOB")  # BOB, USD, etc.

    transaction_id = models.CharField(max_length=80, blank=True)  # referencia pasarela/banco
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    office = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="payments", null=True, blank=True)
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments_taken", null=True, blank=True)

    paid_at = models.DateTimeField(null=True, blank=True)  # cuando se confirmó
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ticket", "status"]),
            models.Index(fields=["method"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"PAY {self.id} • {self.ticket_id} • {self.amount} {self.currency}"

    # Agregados útiles
    @property
    def refunded_total(self) -> Decimal:
        total = (
            self.refunds.filter(status=Refund.STATUS_CONFIRMED)
            .aggregate(s=models.Sum("amount"))
            .get("s") or Decimal("0.00")
        )
        return Decimal(total).quantize(Decimal("0.01"))

    @property
    def refundable_remaining(self) -> Decimal:
        return (self.amount - self.refunded_total).quantize(Decimal("0.01"))

    # Validaciones
    def clean(self):
        super().clean()

        if self.amount is None or self.amount <= 0:
            raise ValidationError("El monto del pago debe ser mayor a 0.")

        if self.ticket and self.ticket.status in [Ticket.STATUS_CANCELLED, Ticket.STATUS_NO_SHOW]:
            raise ValidationError("No se puede registrar un pago para un ticket anulado o no presentado.")

        # Evitar pagar por encima del saldo del ticket (considerando otros pagos confirmados)
        if self.ticket_id and self.amount:
            # Suma pagos confirmados (incluye este si ya está confirmado en memoria)
            confirmed_sum = (
                Payment.objects.filter(ticket_id=self.ticket_id, status__in=[self.STATUS_CONFIRMED, self.STATUS_PARTIALLY_REFUNDED, self.STATUS_REFUNDED])
                .exclude(pk=self.pk)
                .aggregate(s=models.Sum("amount"))
                .get("s") or Decimal("0.00")
            )
            # Ajusta por devoluciones previas a nivel de ticket
            refunds_sum = (
                Refund.objects.filter(payment__ticket_id=self.ticket_id, status=Refund.STATUS_CONFIRMED)
                .aggregate(s=models.Sum("amount"))
                .get("s") or Decimal("0.00")
            )
            net_paid = Decimal(confirmed_sum) - Decimal(refunds_sum)
            due = (self.ticket.price - net_paid).quantize(Decimal("0.01"))

            if self.status in [self.STATUS_CONFIRMED, self.STATUS_PARTIALLY_REFUNDED, self.STATUS_REFUNDED]:
                if self.amount > self.ticket.price:
                    raise ValidationError("Un pago no puede superar el precio total del ticket.")
                if self.amount > due:
                    # Permitimos que la confirmación exacta complete, pero no sobregire.
                    raise ValidationError("El pago excede el saldo pendiente del ticket.")

    def save(self, *args, **kwargs):
        self.full_clean()
        # marcar paid_at si se confirma
        if self.status == self.STATUS_CONFIRMED and self.paid_at is None:
            self.paid_at = timezone.now()
        ret = super().save(*args, **kwargs)

        # Actualizar estado del ticket segun neto pagado
        t = self.ticket
        if t:
            # Forzar recálculo y guardar estado/paid_at si corresponde
            t.save()

        return ret


# ======================================================
# Receipt (Recibo) - 1:1 con Payment
# ======================================================
class Receipt(models.Model):
    STATUS_ISSUED = "ISSUED"
    STATUS_VOID = "VOID"

    STATUS_CHOICES = [
        (STATUS_ISSUED, "Emitido"),
        (STATUS_VOID, "Anulado"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="receipt")
    number = models.CharField(max_length=40, unique=True, db_index=True)  # correlativo/serie
    issued_at = models.DateTimeField(default=timezone.now)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default="BOB")

    issuer_office = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="receipts")
    issuer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="receipts_issued")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ISSUED)
    notes = models.CharField(max_length=160, blank=True)

    # 📎 Archivo PDF del recibo (Cloudinary)
    receipt_pdf = CloudinaryField("receipt_pdf", folder="sales/receipts", blank=True, null=True)

    class Meta:
        ordering = ["-issued_at"]
        indexes = [
            models.Index(fields=["number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["issued_at"]),
        ]

    def __str__(self):
        return f"REC {self.number} • {self.total_amount} {self.currency}"

    def clean(self):
        super().clean()
        if not self.payment_id:
            raise ValidationError("El recibo debe estar asociado a un pago.")
        if self.total_amount is None or self.total_amount <= 0:
            raise ValidationError("El monto del recibo debe ser mayor a 0.")
        if self.payment and self.payment.status not in [Payment.STATUS_CONFIRMED, Payment.STATUS_PARTIALLY_REFUNDED, Payment.STATUS_REFUNDED]:
            raise ValidationError("Solo se puede emitir recibo para pagos confirmados.")
        # Por claridad, usualmente total_amount == payment.amount (o el neto si manejas comisiones/impuestos)
        if self.payment and self.total_amount > self.payment.amount:
            raise ValidationError("El monto del recibo no puede exceder al pago.")


# ======================================================
# Refund (Devolución)
# ======================================================
class Refund(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pendiente"),
        (STATUS_CONFIRMED, "Confirmada"),
        (STATUS_FAILED, "Fallida"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default="BOB")

    reason = models.CharField(max_length=160, blank=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="refunds_processed", null=True, blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # 📎 Archivo PDF de la devolución (Cloudinary)
    refund_pdf = CloudinaryField("refund_pdf", folder="sales/refunds", blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["payment", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"REF {self.id} • {self.amount} {self.currency}"

    def clean(self):
        super().clean()
        if self.amount is None or self.amount <= 0:
            raise ValidationError("El monto de la devolución debe ser mayor a 0.")

        if not self.payment_id:
            raise ValidationError("La devolución debe estar ligada a un pago.")

        # Solo se reembolsa pagos confirmados o parcialmente reembolsados
        if self.payment.status not in [Payment.STATUS_CONFIRMED, Payment.STATUS_PARTIALLY_REFUNDED]:
            raise ValidationError("Solo se puede devolver pagos confirmados.")

        # No exceder el saldo reembolsable del pago
        if self.amount > self.payment.refundable_remaining:
            raise ValidationError("El monto excede el saldo reembolsable del pago.")

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.status == self.STATUS_CONFIRMED and self.processed_at is None:
            self.processed_at = timezone.now()
        ret = super().save(*args, **kwargs)

        # Actualizar estado del Payment según total reembolsado
        p = self.payment
        if p:
            refunded = p.refunded_total
            if refunded == Decimal("0.00"):
                pass
            elif refunded < p.amount:
                if p.status != Payment.STATUS_PARTIALLY_REFUNDED:
                    p.status = Payment.STATUS_PARTIALLY_REFUNDED
                    p.save(update_fields=["status"])
            else:
                # reembolsado completamente
                if p.status != Payment.STATUS_REFUNDED:
                    p.status = Payment.STATUS_REFUNDED
                    p.save(update_fields=["status"])

            # Forzar actualización del estado del ticket (puede pasar de PAID a RESERVED si quedó saldo)
            t = p.ticket
            if t:
                t.save()

        return ret
