# apps/catalog/utils.py
from django.db import transaction
from .models import Office, CrewMember
from .constants import DEPT_PREFIX

def _normalize_dept(dept: str) -> str:
    return (dept or "").strip().upper()

def _prefix_for_department(dept: str) -> str:
    key = _normalize_dept(dept)
    return DEPT_PREFIX.get(key, (key[:3] if key else "OFI")).upper()

def next_office_code_for_department(department: str, width: int = 2) -> str:
    prefix = _prefix_for_department(department)
    # ejemplo: LPZ-01
    like = f"{prefix}-"
    last_code = (
        Office.objects
        .filter(code__startswith=like)
        .order_by("-code")  # ordena lexicográficamente; con zero-pad funciona bien
        .values_list("code", flat=True)
        .first()
    )
    last_num = 0
    if last_code:
        try:
            last_num = int(last_code.split("-")[-1])
        except Exception:
            last_num = 0
    new_num = last_num + 1
    return f"{prefix}-{new_num:0{width}d}"

# catalog/utils.py
import re
from django.db import transaction, IntegrityError
from .models import Bus

_PAD = 4
_PREFIX = "BUS-"
_NUM_RE = re.compile(r"(\d+)$")

def next_bus_code_global() -> str:
    """
    Genera el siguiente código global: BUS-0001, BUS-0002, ...
    Asume zero-pad constante para permitir orden lexicográfico.
    """
    last = (
        Bus.objects
        .filter(code__startswith=_PREFIX)
        .values_list("code", flat=True)
        .order_by("-code")  # con zero-pad, el orden lexicográfico funciona
        .first()
    )
    if last:
        m = _NUM_RE.search(last)
        n = int(m.group(1)) if m else 0
    else:
        n = 0
    return f"{_PREFIX}{(n + 1):0{_PAD}d}"

def create_bus_with_code(validated_data: dict, retries: int = 3) -> Bus:
    """
    Crea Bus generando code de forma transaccional con reintentos.
    """
    for _ in range(retries):
        validated_data["code"] = next_bus_code_global()
        try:
            with transaction.atomic():
                return Bus.objects.create(**validated_data)
        except IntegrityError:
            # otro proceso tomó el mismo code -> reintenta
            continue
    raise IntegrityError("No se pudo generar un código único para Bus.")


# ======= NUEVO: CREWMEMBER =======
_CREW_PAD = 4
_CREW_PREFIX = "EMP-"              # p.ej. EMP-0001, EMP-0002, ...
_CREW_NUM_RE = re.compile(r"(\d+)$")

def next_crew_code_global() -> str:
    """
    Genera el siguiente código global de empleado con zero-pad:
    EMP-0001, EMP-0002, ...
    """
    last = (
        CrewMember.objects
        .filter(code__startswith=_CREW_PREFIX)
        .values_list("code", flat=True)
        .order_by("-code")
        .first()
    )
    if last:
        m = _CREW_NUM_RE.search(last)
        n = int(m.group(1)) if m else 0
    else:
        n = 0
    return f"{_CREW_PREFIX}{(n + 1):0{_CREW_PAD}d}"

def create_crewmember_with_code(validated_data: dict, retries: int = 3) -> CrewMember:
    """
    Crea un CrewMember generando code de forma transaccional con reintentos,
    para evitar colisiones en concurrencia.
    """
    for _ in range(retries):
        validated_data["code"] = next_crew_code_global()
        try:
            with transaction.atomic():
                return CrewMember.objects.create(**validated_data)
        except IntegrityError:
            continue
    raise IntegrityError("No se pudo generar un código único para CrewMember.")
