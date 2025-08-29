from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PassengerViewSet, PassengerRelationViewSet

router = DefaultRouter()
router.register(r"passengers", PassengerViewSet, basename="passenger")
router.register(r"relations", PassengerRelationViewSet, basename="passenger-relation")

urlpatterns = [
    path("", include(router.urls)),
]
