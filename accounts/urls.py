from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LoginView, MeView, ChangePasswordView, UserViewSet, AuditLogViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='users')
router.register(r'audit', AuditLogViewSet, basename='audit')

urlpatterns = [
    path('auth/login', LoginView.as_view()),
    path('auth/me', MeView.as_view()),
    path('auth/change-password', ChangePasswordView.as_view()),
    path('', include(router.urls)),
]
