from django.contrib.auth import authenticate, password_validation, get_user_model
from rest_framework import serializers
from .models import AuditLog

User = get_user_model()

# ---------- AUTH ----------
class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data['username'], password=data['password'])
        if not user:
            raise serializers.ValidationError('Credenciales inválidas')
        if not user.is_active:
            raise serializers.ValidationError('Usuario inactivo')
        data['user'] = user
        return data


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'first_name', 'last_name', 'email', 'role', 'must_change_password')


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    def validate_new_password(self, value):
        password_validation.validate_password(value)
        return value


# ---------- USERS (ADMIN CRUD) ----------
class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id','username','email','first_name','last_name','role','is_active','date_joined','last_login')


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(choices=User._meta.get_field('role').choices, default='VEND')

    class Meta:
        model = User
        fields = ('username','email','first_name','last_name','role','password','is_active')

    def validate_email(self, value):
        if value and User.objects.filter(email=value).exists():
            raise serializers.ValidationError('Este email ya está en uso.')
        return value

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
    class Meta:
        model = User
        fields = ('email','first_name','last_name','role','is_active')

    def update(self, instance, validated_data):
        role = validated_data.get('role', instance.role)
        instance = super().update(instance, validated_data)
        if role == 'ADMIN':
            instance.is_staff = True
            instance.is_superuser = True
        else:
            instance.is_staff = False
            instance.is_superuser = False
        instance.save(update_fields=['is_staff','is_superuser'])
        return instance


class AdminSetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True)
    def validate_new_password(self, value):
        password_validation.validate_password(value)
        return value


# ---------- PERFIL PROPIO ----------
class UserSelfSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id','username','email','first_name','last_name')
        read_only_fields = ('id','username')


# ---------- AUDIT (solo lectura) ----------
class AuditLogSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)
    class Meta:
        model = AuditLog
        fields = ('id','created_at','user','user_username','action','entity','record_id','extra')
