# apps/catalog/urls.py
from rest_framework.routers import DefaultRouter
from .views import (
    OfficeViewSet, BusViewSet, RouteViewSet, DepartureViewSet,
    CrewMemberViewSet, DriverLicenseViewSet, DepartureAssignmentViewSet
)

router = DefaultRouter()
router.register(r"offices", OfficeViewSet, basename="office")
router.register(r"buses", BusViewSet, basename="bus")
router.register(r"routes", RouteViewSet, basename="route")
router.register(r"departures", DepartureViewSet, basename="departure")

router.register(r"crew", CrewMemberViewSet, basename="crew")
router.register(r"licenses", DriverLicenseViewSet, basename="license")
router.register(r"assignments", DepartureAssignmentViewSet, basename="assignment")

urlpatterns = router.urls
