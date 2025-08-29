from rest_framework import serializers
from .models import Passenger, PassengerRelation

class PassengerMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Passenger
        fields = ("id", "nombres", "apellidos", "tipo_doc", "nro_doc")

class PassengerSerializer(serializers.ModelSerializer):
    es_menor = serializers.BooleanField(read_only=True)
    # lectura: lista de apoderados (compacta)
    apoderados_list = PassengerMiniSerializer(source="apoderados", many=True, read_only=True)

    class Meta:
        model = Passenger
        fields = (
            "id", "tipo_doc", "nro_doc", "nombres", "apellidos",
            "fecha_nac", "telefono", "email", "activo", "creado_en",
            "es_menor", "apoderados_list",
        )
        read_only_fields = ("id", "creado_en", "es_menor", "apoderados_list")

class PassengerRelationSerializer(serializers.ModelSerializer):
    menor_det = PassengerMiniSerializer(source="menor", read_only=True)
    apoderado_det = PassengerMiniSerializer(source="apoderado", read_only=True)

    class Meta:
        model = PassengerRelation
        fields = (
            "id", "menor", "apoderado",
            "parentesco", "es_tutor_legal",
            "vigente_desde", "vigente_hasta",
            "observaciones",
            "menor_det", "apoderado_det",
        )
