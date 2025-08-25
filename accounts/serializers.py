from django.contrib.auth import authenticate, password_validation, get_user_model
from django.utils import timezone
from rest_framework import serializers

from .models import AuditLog
from catalog.models import Office  # 👈 NUEVO: para validar office

User = get_user_model()

# ---------- AUTH ----------
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email = data["email"].strip().lower()
        password = data["password"]

        user = User.objects.filter(email__iexact=email).first()
        if not user:
            raise serializers.ValidationError("Credenciales inválidas")

        user = authenticate(username=user.get_username(), password=password)
        if not user:
            raise serializers.ValidationError("Credenciales inválidas")
        if not user.is_active:
            raise serializers.ValidationError("Usuario inactivo")

        data["user"] = user
        return data


# ---------- HELPERS ----------
REQUIRES_OFFICE = {"CAJE", "VEND"}

def _validate_office_by_role(role: str | None, office: Office | None):
    if role in REQUIRES_OFFICE and office is None:
        raise serializers.ValidationError({"office": "Esta función requiere asignar una oficina."})
    return office


# ---------- ME ----------
class MeSerializer(serializers.ModelSerializer):
    office_name = serializers.CharField(source='office.name', read_only=True)

    class Meta:
        model = User
        fields = ('id','username','first_name','last_name','email','role','must_change_password','office','office_name')


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    def validate_new_password(self, value):
        password_validation.validate_password(value)
        return value


# ---------- USERS (ADMIN CRUD) ----------
class UserListSerializer(serializers.ModelSerializer):
    office_name = serializers.CharField(source='office.name', read_only=True)

    class Meta:
        model = User
        fields = ('id','username','email','first_name','last_name','role','is_active',
                  'date_joined','last_login','office','office_name')


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(choices=User._meta.get_field('role').choices, default='VEND')
    office_name = serializers.CharField(source='office.name', read_only=True)

    class Meta:
        model = User
        fields = ('username','email','first_name','last_name','role','password','is_active','office','office_name')

    def validate_email(self, value):
        if value and User.objects.filter(email=value).exists():
            raise serializers.ValidationError('Este email ya está en uso.')
        return value

    def validate(self, attrs):
        role = attrs.get('role')
        office = attrs.get('office')
        _validate_office_by_role(role, office)
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        if user.role == 'ADMIN':
            user.is_staff = True
            user.is_superuser = True
        else:
            user.is_staff = False
            user.is_superuser = False
        user.save()
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    office_name = serializers.CharField(source='office.name', read_only=True)

    class Meta:
        model = User
        fields = ('email','first_name','last_name','role','is_active','password','office','office_name')

    def validate_password(self, value):
        if not value:
            return value
        password_validation.validate_password(value)
        return value

    def validate(self, attrs):
        # role puede venir o no en PATCH; si no viene, usa el actual
        role = attrs.get('role', getattr(self.instance, 'role', None))
        office = attrs.get('office', getattr(self.instance, 'office', None))
        _validate_office_by_role(role, office)
        return attrs

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        role = validated_data.get('role', instance.role)

        instance = super().update(instance, validated_data)

        # flags por rol
        if role == 'ADMIN':
            instance.is_staff = True
            instance.is_superuser = True
            # Si quisieras limpiar la oficina al pasar a ADMIN, descomenta:
            # instance.office = None
        else:
            instance.is_staff = False
            instance.is_superuser = False

        update_fields = ['is_staff','is_superuser']

        if password:
            instance.set_password(password)
            instance.last_password_change = timezone.now()
            instance.must_change_password = False
            update_fields += ['password','last_password_change','must_change_password']

        # Si cambiaste office vía validated_data ya está aplicada por el super().update()
        # Si agregaste lógica para limpiar office en ADMIN, recuerda añadir 'office' a update_fields.

        instance.save(update_fields=update_fields)
        return instance


class AdminSetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True)
    def validate_new_password(self, value):
        password_validation.validate_password(value)
        return value


# ---------- PERFIL PROPIO ----------
class UserSelfSerializer(serializers.ModelSerializer):
    office_name = serializers.CharField(source='office.name', read_only=True)

    class Meta:
        model = User
        fields = ('id','username','email','first_name','last_name','office','office_name')
        read_only_fields = ('id','username')


# ---------- AUDIT (solo lectura) ----------
class AuditLogSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)
    class Meta:
        model = AuditLog
        fields = ('id','created_at','user','user_username','action','entity','record_id','extra')
