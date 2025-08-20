from datetime import timedelta
from django.utils import timezone
from rest_framework import views, generics, viewsets, decorators, response, status, permissions
from rest_framework_simplejwt.tokens import RefreshToken
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter

from django.contrib.auth import get_user_model
from .models import AuditLog
from .serializers import (
    LoginSerializer, MeSerializer, ChangePasswordSerializer,
    UserListSerializer, UserCreateSerializer, UserUpdateSerializer,
    UserSelfSerializer, AdminSetPasswordSerializer, AuditLogSerializer
)
from .permissions import IsAdmin

User = get_user_model()
PASSWORD_MAX_AGE_DAYS = 60  # política de caducidad

# ---------- AUTH ----------
class LoginView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        s = LoginSerializer(data=request.data); s.is_valid(raise_exception=True)
        user = s.validated_data['user']

        # marcar caducidad si corresponde
        last = user.last_password_change
        if (last is None) or (timezone.now() - (last or timezone.now()) > timedelta(days=PASSWORD_MAX_AGE_DAYS)):
            user.must_change_password = True
            user.save(update_fields=['must_change_password'])

        refresh = RefreshToken.for_user(user)
        # Audit LOGIN
        AuditLog.objects.create(user=user, action='LOGIN', entity='Auth', record_id=str(user.id), extra={'ip': request.META.get('REMOTE_ADDR')})
        return response.Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': MeSerializer(user).data
        })


class MeView(generics.RetrieveAPIView):
    serializer_class = MeSerializer
    def get_object(self): return self.request.user


class ChangePasswordView(views.APIView):
    def post(self, request):
        s = ChangePasswordSerializer(data=request.data); s.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(s.validated_data['old_password']):
            return response.Response({'detail':'Contraseña actual incorrecta'}, status=400)
        user.set_password(s.validated_data['new_password'])
        user.last_password_change = timezone.now()
        user.must_change_password = False
        user.save(update_fields=['password','last_password_change','must_change_password'])
        return response.Response({'detail':'Contraseña actualizada'})


# ---------- USERS (ADMIN CRUD + perfil propio) ----------
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('id')
    permission_classes = [IsAdmin]

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        if self.action in ['update','partial_update']:
            return UserUpdateSerializer
        if self.action in ['list','retrieve']:
            return UserListSerializer
        return UserListSerializer

    @decorators.action(detail=False, methods=['get','patch'], url_path='me', permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        if request.method == 'GET':
            return response.Response(UserSelfSerializer(request.user).data)
        ser = UserSelfSerializer(request.user, data=request.data, partial=True)
        ser.is_valid(raise_exception=True); ser.save()
        return response.Response(ser.data)

    @decorators.action(detail=True, methods=['post'], url_path='set-password')
    def set_password(self, request, pk=None):
        ser = AdminSetPasswordSerializer(data=request.data); ser.is_valid(raise_exception=True)
        user = self.get_object()
        user.set_password(ser.validated_data['new_password'])
        user.last_password_change = timezone.now()
        user.must_change_password = False
        user.save(update_fields=['password','last_password_change','must_change_password'])
        return response.Response({'detail':'Contraseña actualizada por admin'})


# ---------- AUDIT (solo lectura Admin) ----------
class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related('user').all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_fields = {
        'action': ['exact'],
        'entity': ['exact','icontains'],
        'user': ['exact'],
        'created_at': ['date__gte','date__lte'],
    }
    search_fields = ['record_id','entity','user__username']
    ordering_fields = ['created_at','user']
    ordering = ['-created_at']
