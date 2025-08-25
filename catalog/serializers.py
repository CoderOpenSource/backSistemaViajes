

# ---------- OFFICES ----------
# apps/catalog/serializers.py
from django.db import transaction, IntegrityError
from rest_framework import serializers
from .models import Office, Bus, Route, RouteStop, Departure
from .utils import next_office_code_for_department,create_bus_with_code, create_crewmember_with_code
from .models import CrewMember, DriverLicense, DepartureAssignment
class OfficeSerializer(serializers.ModelSerializer):
    # code es generado => solo lectura hacia el cliente
    code = serializers.CharField(read_only=True)

    class Meta:
        model = Office
        fields = (
            "id", "code", "name",
            "department", "province", "municipality", "locality",
            "address", "location_url", "phone",
            "active", "created_at", "updated_at",
        )
        read_only_fields = ("created_at", "updated_at", "code")

    def validate(self, attrs):
        # Requerimos department para poder generar el code
        if self.instance is None:  # solo al crear
            dep = attrs.get("department")
            if not (dep and dep.strip()):
                raise serializers.ValidationError({"department": "Este campo es requerido para generar el código."})
        return attrs

    def create(self, validated_data):
        # Genera code en transacción para minimizar colisiones
        department = validated_data.get("department", "")
        for _ in range(3):  # pequeño reintento ante race-condition
            code = next_office_code_for_department(department)
            validated_data["code"] = code
            try:
                with transaction.atomic():
                    return Office.objects.create(**validated_data)
            except IntegrityError:
                # si otro proceso tomó el mismo code, intenta el siguiente
                continue
        # si falla tras reintentos:
        raise serializers.ValidationError({"code": "No se pudo generar un código único. Intenta nuevamente."})

    def update(self, instance, validated_data):
        # code inmutable
        validated_data.pop("code", None)
        return super().update(instance, validated_data)

# serializers.py (fragmento)

from rest_framework import serializers


class BusSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)  # <- código generado, inmutable

    class Meta:
        model = Bus
        fields = (
            "id", "code", "model", "year", "plate", "chassis_number",
            "capacity", "active", "notes", "created_at"
        )
        read_only_fields = ("created_at", "code")

    def create(self, validated_data):
        try:
            return create_bus_with_code(validated_data)
        except IntegrityError:
            raise serializers.ValidationError({"code": "No se pudo generar un código único. Intenta nuevamente."})

    def update(self, instance, validated_data):
        validated_data.pop("code", None)  # code es inmutable
        return super().update(instance, validated_data)



# ---------- ROUTES + STOPS (nested) ----------
class RouteStopSerializer(serializers.ModelSerializer):
    office_code = serializers.CharField(source="office.code", read_only=True)
    office_name = serializers.CharField(source="office.name", read_only=True)

    class Meta:
        model = RouteStop
        fields = ("id", "office", "office_code", "office_name", "order", "scheduled_offset_min")


class RouteSerializer(serializers.ModelSerializer):
    # Paradas anidadas (lectura y escritura)
    stops = RouteStopSerializer(many=True)

    origin_code = serializers.CharField(source="origin.code", read_only=True)
    destination_code = serializers.CharField(source="destination.code", read_only=True)

    class Meta:
        model = Route
        fields = (
            "id", "name", "origin", "origin_code", "destination", "destination_code",
            "active", "created_at", "stops"
        )
        read_only_fields = ("created_at",)

    def validate(self, attrs):
        # Si vienen stops en create/update, validar que no repitan offices y orden
        stops_data = self.initial_data.get("stops")
        if stops_data:
            seen_offices = set()
            seen_orders = set()
            for s in stops_data:
                off = s.get("office")
                ord_ = s.get("order")
                if off in seen_offices:
                    raise serializers.ValidationError({"stops": "No puede repetirse la misma oficina en la ruta."})
                if ord_ in seen_orders:
                    raise serializers.ValidationError({"stops": "No puede repetirse el mismo 'order'."})
                seen_offices.add(off)
                seen_orders.add(ord_)
        return attrs

    def create(self, validated_data):
        stops_data = validated_data.pop("stops", [])
        route = Route.objects.create(**validated_data)
        # bulk create stops
        for s in stops_data:
            RouteStop.objects.create(route=route, **s)
        return route

    def update(self, instance, validated_data):
        stops_data = validated_data.pop("stops", None)
        instance = super().update(instance, validated_data)

        # Si mandan stops, reemplazamos el set completo
        if stops_data is not None:
            instance.stops.all().delete()
            bulk = [RouteStop(route=instance, **s) for s in stops_data]
            RouteStop.objects.bulk_create(bulk)
        return instance


# ---------- DEPARTURES ----------
class DepartureSerializer(serializers.ModelSerializer):
    route_name = serializers.CharField(source="route.name", read_only=True)
    bus_code = serializers.CharField(source="bus.code", read_only=True)
    bus_plate = serializers.CharField(source="bus.plate", read_only=True)
    driver_username = serializers.CharField(source="driver.username", read_only=True)

    class Meta:
        model = Departure
        fields = (
            "id", "route", "route_name", "bus", "bus_code", "bus_plate",
            "driver", "driver_username",
            "scheduled_departure_at", "actual_departure_at",
            "status", "capacity_snapshot", "notes",
            "created_at",
        )
        read_only_fields = ("capacity_snapshot", "created_at")

from django.db import IntegrityError
from rest_framework import serializers

from .models import CrewMember, DriverLicense, DepartureAssignment, Office
from .utils import create_crewmember_with_code
# from .serializers import DepartureSerializer  # ⚠ si esto genera import circular, quítalo

# ---------- CREW (Tripulación) ----------
class CrewMemberSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)              # generado automáticamente
    full_name = serializers.SerializerMethodField(read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    # NUEVO: FK a Office (editable por id) + lecturas convenientes
    office = serializers.PrimaryKeyRelatedField(
        queryset=Office.objects.all(),
        required=False,
        allow_null=True,
    )
    office_code = serializers.CharField(source="office.code", read_only=True)
    office_name = serializers.CharField(source="office.name", read_only=True)

    # Mantener ImageField para subida por multipart; devolveremos URL en to_representation
    photo = serializers.ImageField(required=False, allow_null=True, use_url=True)

    class Meta:
        model = CrewMember
        fields = (
            "id", "code",
            "first_name", "last_name", "full_name",
            "national_id", "phone", "address", "birth_date",
            "role", "role_display",
            "office", "office_code", "office_name",   # 👈 NUEVOS
            "photo",
            "active",
            "created_at", "updated_at",
        )
        read_only_fields = ("created_at", "updated_at", "code")

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def to_representation(self, instance):
        """Forzar que `photo` sea URL absoluta si aplica."""
        data = super().to_representation(instance)
        request = self.context.get("request")

        if getattr(instance, "photo", None) and getattr(instance.photo, "url", None):
            url = instance.photo.url
            if request and url and not str(url).startswith(("http://", "https://")):
                url = request.build_absolute_uri(url)
            data["photo"] = url
        else:
            data["photo"] = None

        return data

    def create(self, validated_data):
        # print(">> RAW validated_data en create:", validated_data)
        try:
            return create_crewmember_with_code(validated_data)
        except IntegrityError:
            raise serializers.ValidationError(
                {"code": "No se pudo generar un código único. Intenta nuevamente."}
            )

    def update(self, instance, validated_data):
        validated_data.pop("code", None)  # code inmutable
        return super().update(instance, validated_data)

# ---------- DRIVER LICENSE (1:N con fotos en Cloudinary) ----------
class DriverLicenseSerializer(serializers.ModelSerializer):
    crew_code = serializers.CharField(source="crew_member.code", read_only=True)
    crew_name = serializers.SerializerMethodField(read_only=True)
    crew_role = serializers.CharField(source="crew_member.role", read_only=True)

    # ✅ aceptar subida por multipart y exponer URL
    front_image = serializers.ImageField(required=False, allow_null=True, use_url=True)
    back_image  = serializers.ImageField(required=False, allow_null=True, use_url=True)

    class Meta:
        model = DriverLicense
        fields = (
            "id",
            "crew_member", "crew_code", "crew_name", "crew_role",
            "number", "category", "issued_at", "expires_at",
            "front_image", "back_image",
            "active", "notes",
        )

    def get_crew_name(self, obj):
        if not obj.crew_member:
            return None
        return f"{obj.crew_member.first_name} {obj.crew_member.last_name}".strip()

    def to_representation(self, instance):
        """Asegura que las imágenes salgan como URL absolutas."""
        data = super().to_representation(instance)
        req = self.context.get("request")

        def absurl(img_field):
            if getattr(instance, img_field, None) and getattr(getattr(instance, img_field), "url", None):
                url = getattr(instance, img_field).url
                if req and url and not str(url).startswith(("http://", "https://")):
                    return req.build_absolute_uri(url)
                return url
            return None

        data["front_image"] = absurl("front_image")
        data["back_image"]  = absurl("back_image")
        return data

    def validate(self, attrs):
        cm = attrs.get("crew_member") or getattr(self.instance, "crew_member", None)
        if cm and cm.role != CrewMember.ROLE_DRIVER:
            raise serializers.ValidationError(
                {"crew_member": "Solo los miembros con rol DRIVER pueden tener licencias."}
            )
        issued  = attrs.get("issued_at",  getattr(self.instance, "issued_at",  None))
        expires = attrs.get("expires_at", getattr(self.instance, "expires_at", None))
        if issued and expires and expires < issued:
            raise serializers.ValidationError(
                {"expires_at": "La fecha de expiración no puede ser anterior a la de emisión."}
            )
        return attrs


# ---------- DEPARTURE ASSIGNMENT (máx 2 por rol con slot) ----------
class DepartureAssignmentSerializer(serializers.ModelSerializer):
    crew_code = serializers.CharField(source="crew_member.code", read_only=True)
    crew_name = serializers.SerializerMethodField(read_only=True)
    crew_role = serializers.CharField(source="crew_member.role", read_only=True)
    departure_info = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DepartureAssignment
        fields = (
            "id",
            "departure", "departure_info",
            "crew_member", "crew_code", "crew_name", "crew_role",
            "role", "slot",
            "assigned_at", "unassigned_at",
            "notes",
        )
        read_only_fields = ("assigned_at",)

    def get_crew_name(self, obj):
        return f"{obj.crew_member.first_name} {obj.crew_member.last_name}".strip()

    def get_departure_info(self, obj):
        d = obj.departure
        if not d:
            return None
        return {
            "id": d.id,
            "route": getattr(d.route, "name", None),
            "bus": getattr(d.bus, "code", None),
            "scheduled": d.scheduled_departure_at,
            "status": d.status,
        }

    def validate(self, attrs):
        """
        Validación amable en serializer (además del model.clean()):
        - el rol enviado debe coincidir con el rol del CrewMember
        - si role=DRIVER, debe tener una licencia vigente para la fecha de salida
        """
        cm = attrs.get("crew_member") or getattr(self.instance, "crew_member", None)
        role = attrs.get("role", getattr(self.instance, "role", None))
        dep = attrs.get("departure") or getattr(self.instance, "departure", None)

        if cm and role and cm.role != role:
            raise serializers.ValidationError(
                {"role": "El rol de la asignación no coincide con el rol del miembro."}
            )

        if role == CrewMember.ROLE_DRIVER and cm and dep:
            date_ref = getattr(dep, "scheduled_departure_at", None)
            licenses = list(cm.licenses.all())
            if not licenses:
                raise serializers.ValidationError({"crew_member": "El chofer no tiene licencias registradas."})
            if date_ref and not any(lic.is_valid_on(date_ref) for lic in licenses):
                raise serializers.ValidationError({"crew_member": "El chofer no tiene una licencia vigente para la fecha de salida."})

        return attrs


# ---------- OPCIONAL: Departure con tripulación embebida ----------
class SimpleCrewMemberReadSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = CrewMember
        fields = ("id", "code", "first_name", "last_name", "full_name", "role", "role_display", "phone", "photo")

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()


class DepartureWithCrewSerializer(DepartureSerializer):
    drivers = SimpleCrewMemberReadSerializer(source="crew_drivers", many=True, read_only=True)
    assistants = SimpleCrewMemberReadSerializer(source="crew_assistants", many=True, read_only=True)

    class Meta(DepartureSerializer.Meta):
        fields = DepartureSerializer.Meta.fields + ("drivers", "assistants",)
