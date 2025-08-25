from datetime import timedelta
from django.utils import timezone
from rest_framework import views, generics, viewsets, decorators, response, status, permissions
from rest_framework_simplejwt.tokens import RefreshToken
from .utils import audit, _client_ip
from django.conf import settings
from django.contrib.auth import get_user_model
from .models import AuditLog
from .serializers import (
    LoginSerializer, MeSerializer, ChangePasswordSerializer,
    UserListSerializer, UserCreateSerializer, UserUpdateSerializer,
    UserSelfSerializer, AdminSetPasswordSerializer, AuditLogSerializer
)
from .permissions import IsAdmin
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

User = get_user_model()

# ---------- AUTH ----------
PASSWORD_MAX_AGE_DAYS = getattr(settings, "PASSWORD_MAX_AGE_DAYS", 90)
REQUIRE_FIRST_LOGIN_CHANGE = getattr(settings, "REQUIRE_FIRST_LOGIN_CHANGE", False)

class LoginView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        s = LoginSerializer(data=request.data); s.is_valid(raise_exception=True)
        user = s.validated_data['user']

        # --- caducidad de contraseña ---
        now = timezone.now()
        must_change = False
        update_fields = []

        # Excepciones opcionales (ej.: superusers nunca forzados)
        # if user.is_superuser:
        #     must_change = False
        # else:
        if user.last_password_change is None:
            if REQUIRE_FIRST_LOGIN_CHANGE:
                must_change = True
            else:
                # Primer login: inicializa la fecha y no fuerces cambio
                user.last_password_change = now
                update_fields.append('last_password_change')
        else:
            max_age = timedelta(days=PASSWORD_MAX_AGE_DAYS)
            if now - user.last_password_change > max_age:
                must_change = True

        if user.must_change_password != must_change:
            user.must_change_password = must_change
            update_fields.append('must_change_password')

        if update_fields:
            user.save(update_fields=update_fields)

        refresh = RefreshToken.for_user(user)
        audit(request, action="LOGIN", entity="Auth", record_id=user.id, user=user)

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
        audit(request, action="CHANGE_PASSWORD", entity="User", record_id=user.id, extra={"scope": "self"})

        return response.Response({'detail':'Contraseña actualizada'})

# ---------- USERS (ADMIN CRUD + perfil propio) ----------
class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdmin]

    # 🔎 habilitar filtros
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['username', 'email', 'first_name', 'last_name', 'role']
    ordering_fields = ['id', 'date_joined', 'username', 'email', 'first_name', 'last_name', 'role']
    ordering = ['-id']  # más recientes primero

    def get_queryset(self):
        # ⛔️ quita el order_by para no anular ordering y ?ordering=
        qs = User.objects.all()
        # no incluir al propio usuario en list
        if getattr(self, "action", None) == "list" and self.request.user.is_authenticated:
            qs = qs.exclude(pk=self.request.user.pk)
        return qs

    # --- AUDIT: create/update/delete ---
    def perform_create(self, serializer):
        instance = serializer.save()
        AuditLog.objects.create(
            user=self.request.user,
            action='CREATE',
            entity='User',
            record_id=str(instance.pk),
            extra={'ip': _client_ip(self.request)}
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        AuditLog.objects.create(
            user=self.request.user,
            action='UPDATE',
            entity='User',
            record_id=str(instance.pk),
            extra={'ip': _client_ip(self.request)}
        )

    def perform_destroy(self, instance):
        rid = instance.pk
        super().perform_destroy(instance)
        AuditLog.objects.create(
            user=self.request.user,
            action='DELETE',
            entity='User',
            record_id=str(rid),
            extra={'ip': _client_ip(self.request)}
        )

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

        # --- AUDIT: el propio usuario editó su perfil
        AuditLog.objects.create(
            user=request.user,
            action='ME_UPDATE',
            entity='User',
            record_id=str(request.user.id),
            extra={'ip': _client_ip(request)}
        )
        return response.Response(ser.data)

    @decorators.action(detail=True, methods=['post'], url_path='set-password')
    def set_password(self, request, pk=None):
        ser = AdminSetPasswordSerializer(data=request.data); ser.is_valid(raise_exception=True)
        user = self.get_object()
        user.set_password(ser.validated_data['new_password'])
        user.last_password_change = timezone.now()
        user.must_change_password = False
        user.save(update_fields=['password','last_password_change','must_change_password'])

        # --- AUDIT: admin cambió contraseña de otro usuario
        AuditLog.objects.create(
            user=request.user,                # quién hace la acción (admin)
            action='SET_PASSWORD',
            entity='User',
            record_id=str(user.id),           # a quién le cambiaron
            extra={'ip': _client_ip(request), 'target': user.username, 'by_admin': True}
        )
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
