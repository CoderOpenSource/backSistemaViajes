# apps/ventas/services.py
from __future__ import annotations
from decimal import Decimal
from typing import Callable, Optional

from django.db import transaction, IntegrityError
from django.db.models import Sum, Q
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import Ticket, Payment, PaymentMethod, Receipt, Refund
from catalog.models import Departure, Seat, Office


# ======================================================
# 1) Crear ticket de forma segura (venta / reserva de asiento)
#    - Transacción atómica
#    - Lock pesimista sobre el Seat (fila) para serializar compradores del mismo asiento
#    - Revalidación de disponibilidad dentro del lock
# ======================================================
@transaction.atomic
def create_ticket_safe(
    *,
    passenger,
    departure_id: int,
    seat_id: int,
    origin_id: int,
    destination_id: int,
    office_sold_id: int,
    seller,
    price: Decimal,
    initial_status: str = Ticket.STATUS_RESERVED,
) -> Ticket:
    """
    Concurrencia: bloquea la fila de Seat antes de verificar/crear.
    Así evitamos doble venta del mismo asiento en la misma salida.

    NOTA: Si vendes sub-tramos en el mismo asiento, además de este lock,
    deberías validar solapamiento de segmentos (origen->destino) bajo el lock.
    """
    # 1) Bloqueo del recurso crítico (Seat)
    seat_locked: Seat = (
        Seat.objects.select_for_update()
        .get(pk=seat_id)
    )

    # 2) Re-chequeo de existencia dentro del lock (excluye tickets anulados)
    #    Si permites liberar asiento al anular, excluimos CANCELLED.
    conflict_exists = Ticket.objects.filter(
        departure_id=departure_id,
        seat_id=seat_locked.id,
    ).exclude(status=Ticket.STATUS_CANCELLED).exists()

    if conflict_exists:
        raise ValidationError("El asiento ya fue vendido/reservado para esta salida.")

    # 3) Crear ticket (el model.clean() también valida reglas de negocio)
    t = Ticket(
        passenger=passenger,
        departure_id=departure_id,
        seat_id=seat_locked.id,
        origin_id=origin_id,
        destination_id=destination_id,
        office_sold_id=office_sold_id,
        seller=seller,
        price=price,
        status=initial_status,
    )
    t.full_clean()
    t.save()
    return t


# ======================================================
# 2) Registrar un pago (con idempotencia opcional por transaction_id)
#    - Transacción atómica
#    - Lock del Ticket para recalcular saldo seguro
#    - Valida sobrepago si se confirma dentro de esta creación
# ======================================================
@transaction.atomic
def record_payment_safe(
    *,
    ticket_id: int,
    method_id: int,
    amount: Decimal,
    currency: str = "BOB",
    cashier=None,
    office_id: Optional[int] = None,
    transaction_id: Optional[str] = None,  # permite idempotencia
    confirm: bool = False,
) -> Payment:
    """
    Concurrencia: bloquea el Ticket para que los cálculos de saldo (pagos previos y devoluciones)
    sean consistentes frente a otros pagos concurrentes.
    Idempotencia: si pasas transaction_id y ya existe un Payment con ese ID, lo retornamos.
    """
    # Idempotencia opcional
    if transaction_id:
        existing = Payment.objects.filter(transaction_id=transaction_id).first()
        if existing:
            return existing

    # 1) Lock del ticket
    ticket: Ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
    if ticket.status in [Ticket.STATUS_CANCELLED, Ticket.STATUS_NO_SHOW]:
        raise ValidationError("No se puede registrar un pago para un ticket anulado o no presentado.")

    # 2) Recalcular saldo (pagos confirmados - devoluciones confirmadas)
    confirmed_sum = (
        Payment.objects
        .filter(ticket=ticket, status__in=[Payment.STATUS_CONFIRMED, Payment.STATUS_PARTIALLY_REFUNDED, Payment.STATUS_REFUNDED])
        .aggregate(s=Sum("amount"))
        .get("s") or Decimal("0.00")
    )
    refunds_sum = (
        Refund.objects
        .filter(payment__ticket=ticket, status=Refund.STATUS_CONFIRMED)
        .aggregate(s=Sum("amount"))
        .get("s") or Decimal("0.00")
    )
    net_paid = Decimal(confirmed_sum) - Decimal(refunds_sum)
    due = (ticket.price - net_paid).quantize(Decimal("0.01"))

    status = Payment.STATUS_CONFIRMED if confirm else Payment.STATUS_PENDING

    # 3) Evitar sobrepago si lo creas como confirmado
    if status == Payment.STATUS_CONFIRMED:
        if amount > ticket.price:
            raise ValidationError("Un pago no puede superar el precio total del ticket.")
        if amount > due:
            raise ValidationError("El pago excede el saldo pendiente del ticket.")

    pay = Payment(
        ticket=ticket,
        method_id=method_id,
        amount=amount,
        currency=currency,
        transaction_id=transaction_id or "",
        status=status,
        office_id=office_id,
        cashier=cashier,
        paid_at=timezone.now() if status == Payment.STATUS_CONFIRMED else None,
    )
    pay.full_clean()
    pay.save()

    # 4) Forzar actualización del ticket (podría quedar PAID si se completó)
    ticket.save()
    return pay


# ======================================================
# 3) Confirmar un pago existente de forma segura
#    - Transacción atómica
#    - Locks: Payment + Ticket
#    - Recalcula saldo y evita sobrepago
# ======================================================
@transaction.atomic
def confirm_payment_safe(*, payment_id: str) -> Payment:
    """
    Concurrencia: bloquea Payment y Ticket asociados.
    Evita que dos confirmaciones simultáneas provoquen sobrepago.
    """
    # Bloqueos
    payment: Payment = Payment.objects.select_for_update().get(pk=payment_id)
    ticket: Ticket = Ticket.objects.select_for_update().get(pk=payment.ticket_id)

    if ticket.status in [Ticket.STATUS_CANCELLED, Ticket.STATUS_NO_SHOW]:
        raise ValidationError("No se puede confirmar pago de un ticket anulado/no-show.")

    if payment.status == Payment.STATUS_CONFIRMED:
        return payment  # idempotente

    # Recalcular saldo vigente
    confirmed_sum = (
        Payment.objects
        .filter(ticket=ticket, status__in=[Payment.STATUS_CONFIRMED, Payment.STATUS_PARTIALLY_REFUNDED, Payment.STATUS_REFUNDED])
        .exclude(pk=payment.pk)
        .aggregate(s=Sum("amount"))
        .get("s") or Decimal("0.00")
    )
    refunds_sum = (
        Refund.objects
        .filter(payment__ticket=ticket, status=Refund.STATUS_CONFIRMED)
        .aggregate(s=Sum("amount"))
        .get("s") or Decimal("0.00")
    )
    net_paid = Decimal(confirmed_sum) - Decimal(refunds_sum)
    due = (ticket.price - net_paid).quantize(Decimal("0.01"))

    if payment.amount > ticket.price:
        raise ValidationError("Un pago no puede superar el precio total del ticket.")
    if payment.amount > due:
        raise ValidationError("El pago excede el saldo pendiente del ticket.")

    # Confirmar
    payment.status = Payment.STATUS_CONFIRMED
    if not payment.paid_at:
        payment.paid_at = timezone.now()
    payment.full_clean()
    payment.save()

    # Actualizar ticket
    ticket.save()
    return payment


# ======================================================
# 4) Crear devolución (refund) de forma segura
#    - Transacción atómica
#    - Lock del Payment padre
#    - Revalida saldo reembolsable y actualiza estados
# ======================================================
@transaction.atomic
def create_refund_safe(
    *,
    payment_id: str,
    amount: Decimal,
    reason: str = "",
    processed_by=None,
    confirm_immediately: bool = True,
) -> Refund:
    """
    Concurrencia: bloquea el Payment antes de calcular el saldo reembolsable.
    """
    payment: Payment = Payment.objects.select_for_update().get(pk=payment_id)

    if payment.status not in [Payment.STATUS_CONFIRMED, Payment.STATUS_PARTIALLY_REFUNDED]:
        raise ValidationError("Solo se puede devolver pagos confirmados.")

    if amount <= 0:
        raise ValidationError("El monto de la devolución debe ser mayor a 0.")

    if amount > payment.refundable_remaining:
        raise ValidationError("El monto excede el saldo reembolsable del pago.")

    refund = Refund(
        payment=payment,
        amount=amount,
        currency=payment.currency,
        reason=reason,
        processed_by=processed_by,
        status=Refund.STATUS_CONFIRMED if confirm_immediately else Refund.STATUS_PENDING,
        processed_at=timezone.now() if confirm_immediately else None,
    )
    refund.full_clean()
    refund.save()  # su save() ya ajusta estado del Payment y fuerza recalcular Ticket
    return refund


# ======================================================
# 5) Emitir recibo de forma segura (numeración + post-commit PDF)
#    - Transacción atómica
#    - Lock del Payment (evita 2 recibos para mismo pago)
#    - La generación/subida del PDF se hace post-commit
# ======================================================
@transaction.atomic
def issue_receipt_safe(
    *,
    payment_id: str,
    number: str,
    issuer_office_id: int,
    issuer,
    total_amount: Optional[Decimal] = None,
    currency: str = "BOB",
    notes: str = "",
    build_pdf_callback: Optional[Callable[[Receipt], None]] = None,
) -> Receipt:
    """
    Concurrencia: bloquea Payment para evitar que dos procesos emitan recibo simultáneamente.
    Numeración: 'number' debe provenir de un generador seguro (secuencia o contador bajo lock).
    Post-commit: el PDF se genera y sube luego del COMMIT para no dejar archivos huérfanos si hay rollback.
    """
    payment: Payment = Payment.objects.select_for_update().get(pk=payment_id)

    # OneToOne ya protege, pero validamos de forma explícita
    if hasattr(payment, "receipt"):
        return payment.receipt  # idempotente

    if payment.status not in [Payment.STATUS_CONFIRMED, Payment.STATUS_PARTIALLY_REFUNDED, Payment.STATUS_REFUNDED]:
        raise ValidationError("Solo se puede emitir recibo para pagos confirmados o similares.")

    amount = total_amount if total_amount is not None else payment.amount
    receipt = Receipt(
        payment=payment,
        number=number,
        total_amount=amount,
        currency=currency,
        issuer_office_id=issuer_office_id,
        issuer=issuer,
        notes=notes,
    )
    receipt.full_clean()
    receipt.save()

    # Generación/subida de PDF fuera de la transacción
    if build_pdf_callback:
        def _post_commit():
            try:
                build_pdf_callback(receipt)
            except Exception:
                # No romper la transacción ya confirmada; loguea en tu proyecto
                pass
        transaction.on_commit(_post_commit)

    return receipt


# ======================================================
# 6) Anular ticket de forma segura
#    - Transacción atómica
#    - Lock del Ticket
#    - Bloquea si hay pagos netos confirmados sin devolver
# ======================================================
@transaction.atomic
def cancel_ticket_safe(*, ticket_id: int) -> Ticket:
    """
    Concurrencia: bloquea Ticket para que el estado no se cruce con pagos/devoluciones concurrentes.
    Política: solo permite anular si el neto pagado es 0 (sin pagos confirmados pendientes).
    Ajusta esto si tu negocio permite otra cosa.
    """
    ticket: Ticket = Ticket.objects.select_for_update().get(pk=ticket_id)

    if ticket.status == Ticket.STATUS_CANCELLED:
        return ticket

    # neto pagado actual (usa agregados como en amount_paid)
    confirmed_sum = (
        Payment.objects
        .filter(ticket=ticket, status__in=[Payment.STATUS_CONFIRMED, Payment.STATUS_PARTIALLY_REFUNDED, Payment.STATUS_REFUNDED])
        .aggregate(s=Sum("amount"))
        .get("s") or Decimal("0.00")
    )
    refunds_sum = (
        Refund.objects
        .filter(payment__ticket=ticket, status=Refund.STATUS_CONFIRMED)
        .aggregate(s=Sum("amount"))
        .get("s") or Decimal("0.00")
    )
    net_paid = Decimal(confirmed_sum) - Decimal(refunds_sum)
    if net_paid > 0:
        raise ValidationError("No se puede anular: existen pagos confirmados no devueltos.")

    ticket.status = Ticket.STATUS_CANCELLED
    ticket.full_clean()
    ticket.save(update_fields=["status"])
    return ticket


# ======================================================
# 7) Marcar No-Show de forma segura
#    - Transacción atómica
#    - Lock del Ticket
# ======================================================
@transaction.atomic
def mark_no_show_safe(*, ticket_id: int) -> Ticket:
    """
    Concurrencia: bloquea Ticket para que el estado no colisione con pagos/cancelación.
    """
    ticket: Ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
    if ticket.status == Ticket.STATUS_CANCELLED:
        raise ValidationError("No se puede marcar no-show un ticket anulado.")
    ticket.status = Ticket.STATUS_NO_SHOW
    ticket.full_clean()
    ticket.save(update_fields=["status"])
    return ticket
