from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import User, AuditLog

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ('username','email','first_name','last_name','role','is_active','is_staff')
    list_filter = ('role','is_active','is_staff','is_superuser')
    search_fields = ('username','email','first_name','last_name')

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at','user','action','entity','record_id')
    list_filter = ('action','entity','created_at')
    search_fields = ('user__username','entity','record_id')
