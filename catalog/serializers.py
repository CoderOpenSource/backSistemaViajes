

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

# apps/catalog/serializers.py
from typing import List
from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import Bus, Seat
from .services import (
                   # tu helper existente para generar code único
    create_seats_from_blocks,
    create_default_seats_for_bus,
    SeatsAlreadyExist,
)


class SeatBlockSerializer(serializers.Serializer):
    """
    Bloque declarativo para crear asientos.
    Ejemplo:
    {
      "deck": 1,
      "kind": "SEMI_CAMA",
      "count": 24,
      "start_number": 1,        # opcional
      "row": 1,                 # opcional (si mapeas grilla)
      "col": 2,                 # opcional
      "is_accessible": false    # opcional
    }
    """
    deck = serializers.IntegerField(min_value=1, max_value=2)
    kind = serializers.ChoiceField(choices=[k for k, _ in Seat.KIND_CHOICES])
    count = serializers.IntegerField(min_value=1)
    start_number = serializers.IntegerField(required=False)
    row = serializers.IntegerField(required=False)
    col = serializers.IntegerField(required=False)
    is_accessible = serializers.BooleanField(required=False, default=False)

# catalog/serializers.py
from typing import List
from django.db import transaction, IntegrityError
from rest_framework import serializers

from .models import Bus, Seat

# serializers.py
from rest_framework import serializers
from django.db import transaction, IntegrityError
from rest_framework import serializers

class BusSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)

    # mapear alias -> campos reales del modelo
    photo_front = serializers.ImageField(source="photo1", required=False, allow_null=True, use_url=True)
    photo_back  = serializers.ImageField(source="photo2", required=False, allow_null=True, use_url=True)
    photo_left  = serializers.ImageField(source="photo3", required=False, allow_null=True, use_url=True)
    photo_right = serializers.ImageField(source="photo4", required=False, allow_null=True, use_url=True)

    seat_blocks = SeatBlockSerializer(many=True, required=False, write_only=True)

    seats_count = serializers.SerializerMethodField(read_only=True)
    seat_blocks_current = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Bus
        fields = (
            "id", "code", "model", "year", "plate", "chassis_number",
            "capacity", "active", "notes", "created_at",
            "photo_front", "photo_back", "photo_left", "photo_right",
            "seat_blocks", "seats_count", "seat_blocks_current",
        )
        read_only_fields = ("created_at", "code", "seats_count", "seat_blocks_current")

    # --- normaliza borrado "" -> None (acepta alias y names crudos) ---
    def validate(self, attrs):
        initial = self.initial_data or {}
        alias_to_source = {
            "photo_front": "photo1",
            "photo_back":  "photo2",
            "photo_left":  "photo3",
            "photo_right": "photo4",
        }
        # también soporta recibir photo1..photo4 directamente
        for key in [*alias_to_source.keys(), "photo1", "photo2", "photo3", "photo4"]:
            if key in initial and initial.get(key) == "":
                attrs[alias_to_source.get(key, key)] = None
        return attrs

    # --- helpers ---
    def _validate_blocks_against_capacity(self, capacity: int, blocks: list[dict]):
        total = sum(int(b.get("count", 0)) for b in (blocks or []))
        if total <= 0:
            raise serializers.ValidationError({"seat_blocks": "La suma de 'count' debe ser mayor a 0."})
        if capacity is None:
            raise serializers.ValidationError({"capacity": "Debes especificar 'capacity'."})
        if total != int(capacity):
            raise serializers.ValidationError({
                "seat_blocks": f"La suma de 'count' ({total}) debe coincidir con 'capacity' ({capacity})."
            })

    def get_seats_count(self, obj: Bus) -> int:
        return getattr(obj, "_seats_count", None) or obj.seats.count()

    def get_seat_blocks_current(self, obj: Bus):
        qs = obj.seats.all().order_by("deck", "kind", "number").values("deck", "kind", "number")
        blocks, last = [], None
        for s in qs:
            dk = (s["deck"], s["kind"]); num = s["number"]
            if last is None:
                last = [dk[0], dk[1], num, num, 1]; continue
            if last[0] == dk[0] and last[1] == dk[1] and num == last[2] + 1:
                last[2] = num; last[4] += 1
            else:
                blocks.append({"deck": last[0], "kind": last[1], "count": last[4], "start_number": last[3]})
                last = [dk[0], dk[1], num, num, 1]
        if last is not None:
            blocks.append({"deck": last[0], "kind": last[1], "count": last[4], "start_number": last[3]})
        return blocks

    # --- URLs absolutas (sobre alias) ---
    def to_representation(self, instance):
        data = super().to_representation(instance)
        req = self.context.get("request")

        def absurl(field):
            f = getattr(instance, field, None)
            if f and hasattr(f, "url"):
                url = f.url
                if req and url and not str(url).startswith(("http://", "https://")):
                    return req.build_absolute_uri(url)
                return url
            return None

        data["photo_front"] = absurl("photo1")
        data["photo_back"]  = absurl("photo2")
        data["photo_left"]  = absurl("photo3")
        data["photo_right"] = absurl("photo4")
        return data

    # --- create ---
    def create(self, validated_data):
        seat_blocks = validated_data.pop("seat_blocks", None)
        if seat_blocks:
            self._validate_blocks_against_capacity(validated_data.get("capacity"), seat_blocks)
        with transaction.atomic():
            bus = create_bus_with_code(validated_data)
            if seat_blocks:
                create_seats_from_blocks(bus, seat_blocks, mode="fail_if_exists")
            else:
                create_default_seats_for_bus(bus, mode="fail_if_exists", deck=1)
            return bus

    # --- update ---
    def update(self, instance, validated_data):
        validated_data.pop("code", None)
        seat_blocks = validated_data.pop("seat_blocks", None)

        if seat_blocks:
            capacity_target = validated_data.get("capacity", instance.capacity)
            self._validate_blocks_against_capacity(capacity_target, seat_blocks)

        with transaction.atomic():
            if "capacity" in validated_data and not seat_blocks:
                new_cap = int(validated_data["capacity"])
                existing = instance.seats.count()
                if new_cap < existing:
                    raise serializers.ValidationError({
                        "capacity": f"No puedes reducir la capacidad a {new_cap} porque ya existen {existing} asientos."
                    })

            bus = super().update(instance, validated_data)
            if seat_blocks:
                create_seats_from_blocks(bus, seat_blocks, mode="replace")
            return bus

# apps/catalog/serializers.py
from django.db import transaction
from rest_framework import serializers
from catalog.models import Route, RouteStop, Office


# ---- ROUTE STOPS (nested) ----
class RouteStopSerializer(serializers.ModelSerializer):
    # lectura cómoda
    office_code = serializers.CharField(source="office.code", read_only=True)
    office_name = serializers.CharField(source="office.name", read_only=True)

    # escritura por id (si quieres también aceptar object completo, quita este campo)
    office = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all())

    class Meta:
        model = RouteStop
        fields = ("id", "office", "office_code", "office_name", "order", "scheduled_offset_min")
        read_only_fields = ("id",)


class RouteSerializer(serializers.ModelSerializer):
    """
    Maneja create/update de Route + stops anidados.
    Reglas:
      - order empieza en 0 y es consecutivo (0..N)
      - primera parada == origin; última parada == destination
      - no se repiten oficinas dentro de la ruta
    """
    stops = RouteStopSerializer(many=True)

    # lectura de códigos (azúcar sintáctico)
    origin_code = serializers.CharField(source="origin.code", read_only=True)
    destination_code = serializers.CharField(source="destination.code", read_only=True)

    class Meta:
        model = Route
        fields = (
            "id", "name",
            "origin", "origin_code",
            "destination", "destination_code",
            "active", "created_at",
            "stops",
        )
        read_only_fields = ("id", "created_at", "origin_code", "destination_code")

    # -------- Validaciones de payload --------
    def _validate_stops_payload(self, *, origin_id: int, destination_id: int, stops_data: list):
        if not stops_data or len(stops_data) < 2:
            raise serializers.ValidationError({"stops": "Debe haber al menos 2 paradas (origen y destino)."})

        # orders consecutivos 0..N
        orders = [s.get("order") for s in stops_data]
        if any(o is None for o in orders):
            raise serializers.ValidationError({"stops": "Cada parada debe incluir 'order'."})
        if sorted(orders) != list(range(len(stops_data))):
            raise serializers.ValidationError({"stops": "El 'order' debe ser consecutivo empezando en 0."})

        # primera = origin, última = destination
        first_office = stops_data[0].get("office")
        last_office = stops_data[-1].get("office")
        if int(first_office) != int(origin_id):
            raise serializers.ValidationError({"stops": "La primera parada (order=0) debe ser la oficina de origen."})
        if int(last_office) != int(destination_id):
            raise serializers.ValidationError({"stops": "La última parada debe ser la oficina de destino."})

        # no repetir oficinas
        off_ids = [int(s.get("office")) for s in stops_data]
        if len(off_ids) != len(set(off_ids)):
            raise serializers.ValidationError({"stops": "No puede repetirse la misma oficina en la ruta."})

        # opcional: forzar oficinas activas (si querés la regla aquí)
        # inactivos = Office.objects.filter(id__in=off_ids, active=False).values_list("code", flat=True)
        # if inactivos:
        #     raise serializers.ValidationError({"stops": f"Oficinas inactivas: {', '.join(inactivos)}"})

    def validate(self, attrs):
        # Para validar necesitamos origin/destination del objeto (create) o instancia (update)
        data = self.initial_data or {}
        stops_data = data.get("stops") or []

        # Determinar origin/destination
        origin_id = data.get("origin") if self.instance is None else (data.get("origin") or self.instance.origin_id)
        destination_id = data.get("destination") if self.instance is None else (data.get("destination") or self.instance.destination_id)

        if origin_id is None or destination_id is None:
            # El propio model ya valida origen != destino; aquí solo exigimos presencia
            raise serializers.ValidationError({"origin/destination": "Debe especificar origin y destination."})

        if stops_data:
            self._validate_stops_payload(origin_id=int(origin_id), destination_id=int(destination_id), stops_data=stops_data)

        return attrs

    # -------- Persistencia --------
    @transaction.atomic
    def create(self, validated_data):
        stops_data = validated_data.pop("stops", [])
        route = Route.objects.create(**validated_data)

        # crear stops en bloque
        bulk = [
            RouteStop(
                route=route,
                office=s["office"],
                order=s["order"],
                scheduled_offset_min=s.get("scheduled_offset_min"),
            )
            for s in stops_data
        ]
        RouteStop.objects.bulk_create(bulk)
        return route

    @transaction.atomic
    def update(self, instance, validated_data):
        stops_data = validated_data.pop("stops", None)

        # actualizar campos simples de Route
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.full_clean()  # respeta CheckConstraint origin != destination, etc.
        instance.save()

        # si mandan stops, reemplazamos el set completo
        if stops_data is not None:
            instance.stops.all().delete()
            bulk = [
                RouteStop(
                    route=instance,
                    office=s["office"],
                    order=s["order"],
                    scheduled_offset_min=s.get("scheduled_offset_min"),
                )
                for s in stops_data
            ]
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
