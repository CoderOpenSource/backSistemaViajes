from rest_framework import serializers
from django.utils import timezone

from .models import Ticket
from passenger.models import Passenger
from catalog.models import Departure, Seat, Office

# --- Serializador de lectura (detallado) ---
class TicketReadSerializer(serializers.ModelSerializer):
    passenger = serializers.SerializerMethodField()
    departure = serializers.SerializerMethodField()
    seat = serializers.SerializerMethodField()
    origin = serializers.SerializerMethodField()
    destination = serializers.SerializerMethodField()
    office_sold = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id", "status", "price",
            "paid_at", "created_at",
            "passenger", "departure", "seat",
            "origin", "destination",
            "office_sold", "seller",
        ]

    # --- helpers anidados livianos (evita N+1 con select_related) ---
    def _office_min(self, office: Office):
        return {"id": str(office.id), "code": office.code, "name": office.name}

    def get_passenger(self, obj: Ticket):
        p: Passenger = obj.passenger
        return {
            "id": str(p.id),
            "document": getattr(p, "document", None),
            "full_name": p.full_name if hasattr(p, "full_name") else f"{p.first_name} {p.last_name}".strip(),
        }

    def get_departure(self, obj: Ticket):
        d: Departure = obj.departure
        return {
            "id": str(d.id),
            "date": getattr(d, "date", None),
            "time": getattr(d, "time", None),
            "route": getattr(d.route, "name", None) if getattr(d, "route", None) else None,
            "bus": getattr(d.bus, "plate", None) if getattr(d, "bus", None) else None,
        }

    def get_seat(self, obj: Ticket):
        s: Seat = obj.seat
        return {"id": str(s.id), "number": s.number, "floor": getattr(s, "floor", None)}

    def get_origin(self, obj: Ticket):
        return self._office_min(obj.origin)

    def get_destination(self, obj: Ticket):
        return self._office_min(obj.destination)

    def get_office_sold(self, obj: Ticket):
        return self._office_min(obj.office_sold)

    def get_seller(self, obj: Ticket):
        u = obj.seller
        return {"id": u.id, "username": u.get_username(), "full_name": getattr(u, "get_full_name", lambda: "")()}


# --- Serializador de escritura (IDs) ---
class TicketWriteSerializer(serializers.ModelSerializer):
    # forzamos IDs en creación/actualización
    passenger = serializers.PrimaryKeyRelatedField(queryset=Passenger.objects.all())
    departure = serializers.PrimaryKeyRelatedField(queryset=Departure.objects.all())
    seat = serializers.PrimaryKeyRelatedField(queryset=Seat.objects.all())
    origin = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all())
    destination = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all())
    office_sold = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all())

    class Meta:
        model = Ticket
        fields = [
            "id",
            "passenger", "departure", "seat",
            "origin", "destination",
            "office_sold", "seller",
            "status", "price", "paid_at",
        ]
        read_only_fields = ["id", "paid_at"]

    def validate(self, data):
        """
        Validaciones extra a nivel API (además de model.clean()).
        - Asegura que el asiento pertenezca al bus de la salida.
        - Origen < destino (ruta).
        - Si status = PAID, setea paid_at.
        """
        departure = data.get("departure") or getattr(self.instance, "departure", None)
        seat = data.get("seat") or getattr(self.instance, "seat", None)
        origin = data.get("origin") or getattr(self.instance, "origin", None)
        destination = data.get("destination") or getattr(self.instance, "destination", None)

        # 1) asiento pertenece al bus de la salida
        if departure and seat and departure.bus_id != seat.bus_id:
            raise serializers.ValidationError("El asiento seleccionado no pertenece al bus de esta salida.")

        # 2) origen/destino pertenecen a la ruta y en orden
        if departure and origin and destination:
            route = departure.route
            stops = {rs.office_id: rs.order for rs in route.stops.all()}
            if origin.id not in stops or destination.id not in stops:
                raise serializers.ValidationError("Origen y/o destino no pertenecen a la ruta de la salida.")
            if stops[origin.id] >= stops[destination.id]:
                raise serializers.ValidationError("El origen debe ser anterior al destino en la ruta.")

        return data

    def create(self, validated_data):
        # seller lo puedes inferir del request user si lo prefieres
        request = self.context.get("request")
        if request and not validated_data.get("seller"):
            validated_data["seller"] = request.user
        # paid_at si viene en estado PAID
        if validated_data.get("status") == Ticket.STATUS_PAID and not validated_data.get("paid_at"):
            validated_data["paid_at"] = timezone.now()
        obj = Ticket(**validated_data)
        obj.full_clean()
        obj.save()
        return obj

    def update(self, instance, validated_data):
        # si cambia a PAID, set paid_at si no tiene
        new_status = validated_data.get("status", instance.status)
        if new_status == Ticket.STATUS_PAID and not instance.paid_at and not validated_data.get("paid_at"):
            validated_data["paid_at"] = timezone.now()
        return super().update(instance, validated_data)


# --- Serializador combinado (autolectura tras crear/editar) ---
class TicketSerializer(serializers.ModelSerializer):
    """
    Úsalo en el ViewSet con get_serializer_class() para:
    - POST/PATCH/PUT => TicketWriteSerializer
    - GET => TicketReadSerializer
    """
    class Meta:
        model = Ticket
        fields = "__all__"
