# apps/ventas/urls.py
from rest_framework.routers import DefaultRouter
from .views import (
    TicketViewSet, PaymentViewSet, PaymentMethodViewSet,
    RefundViewSet, ReceiptViewSet
)

router = DefaultRouter()
router.register(r"tickets", TicketViewSet, basename="ticket")
router.register(r"payment-methods", PaymentMethodViewSet, basename="paymentmethod")
router.register(r"payments", PaymentViewSet, basename="payment")
router.register(r"refunds", RefundViewSet, basename="refund")
router.register(r"receipts", ReceiptViewSet, basename="receipt")

urlpatterns = router.urls
