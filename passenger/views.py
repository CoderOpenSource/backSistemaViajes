from rest_framework import viewsets, filters
from django.db.models import Q
from .models import Passenger, PassengerRelation
from .serializers import PassengerSerializer, PassengerRelationSerializer
# views.py
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from .services import crear_menor_con_apoderado

class PassengerViewSet(viewsets.ModelViewSet):
    queryset = Passenger.objects.all().order_by("-creado_en")
    serializer_class = PassengerSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nombres", "apellidos", "nro_doc", "telefono"]
    ordering_fields = ["creado_en", "nombres", "apellidos"]

    def get_queryset(self):
        qs = super().get_queryset()
        doc = self.request.query_params.get("doc")
        tel = self.request.query_params.get("tel")
        activo = self.request.query_params.get("activo")
        if doc:
            qs = qs.filter(Q(nro_doc__iexact=doc) | Q(nro_doc__icontains=doc))
        if tel:
            qs = qs.filter(telefono__icontains=tel)
        if activo in ("true", "false"):
            qs = qs.filter(activo=(activo == "true"))
        return qs

    @action(detail=False, methods=["get"], url_path="search")
    def search(self, request):
        q = request.query_params.get("q", "")
        limit = int(request.query_params.get("page_size", 10))
        qs = (
            Passenger.objects.filter(
                Q(nro_doc__icontains=q) |
                Q(nombres__icontains=q) |
                Q(apellidos__icontains=q) |
                Q(telefono__icontains=q)
            )
            .order_by("-creado_en")[:limit]
        )
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)

    @action(detail=False, methods=["post"], url_path="crear-menor-con-apoderado")
    def crear_menor_con_apoderado_action(self, request):
        data_menor = request.data.get("menor")
        data_apoderado = request.data.get("apoderado")
        if not data_menor or not data_apoderado:
            return Response(
                {"error": "Faltan datos de menor o apoderado"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            menor = crear_menor_con_apoderado(data_menor, data_apoderado)
            ser = self.get_serializer(menor)
            return Response(ser.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class PassengerRelationViewSet(viewsets.ModelViewSet):
    queryset = PassengerRelation.objects.select_related("menor", "apoderado").all()
    serializer_class = PassengerRelationSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        # filtrar por menor o apoderado vía query params
        menor = self.request.query_params.get("menor")
        apoderado = self.request.query_params.get("apoderado")
        if menor:
            qs = qs.filter(menor_id=menor)
        if apoderado:
            qs = qs.filter(apoderado_id=apoderado)
        return qs
