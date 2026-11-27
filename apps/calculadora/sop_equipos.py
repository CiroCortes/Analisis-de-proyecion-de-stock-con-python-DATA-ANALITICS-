"""Motor de dominio S&OP Equipos (Todas las Marcas) — Clean Architecture & DRY.

Fuente única de verdad: nuestra base de datos local alimentada desde el Datalake (SAP).
Agrupa estrictamente por el Maestro SAP (`ProductSKU.familia`, `subfamilia`, `modelo`),
sin crear tablas paralelas ni modelos inventados.

Capas internas:
1. Políticas y reglas puras de negocio (umbrales, semáforo, evaluación de propuestas).
2. Catálogo dinámico de taxonomía SAP (grupos y marcas inferidas desde `ProductSKU`).
3. Carga en lote (batch queries, cero N+1) desde BD.
4. Agregación consolidada por modelo SAP + KPIs macro + exportación estructurada.
"""
import datetime
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.inventory.models import ProductSKU
from apps.inventory.stock_actual_models import StockActual
from .models import (
    CargaDatos,
    CompromisoDetalle,
    ConsumoMensual,
    LineaSolicitud,
    OCAbierta,
    ParametroCompra,
    PresupuestoSOP,
    PropuestaCompraSOP,
    Proveedor,
    SolicitudCompra,
    VentaMensual,
)

# ── 1. Políticas de negocio (Única Fuente de Verdad) ─────────────────────────

CLASE_EQUIPOS = '1'
MESES_BACKLOG_VIGENTE = 12
COBERTURA_SIN_VENTA = 999.0
COSTO_FALLBACK_USD = 100000.0

UMBRAL_SOBRESTOCK_MESES = 12.0
UMBRAL_PRECAUCION_MESES = 6.0
UMBRAL_OPTIMO_MESES = 3.0

BODEGAS_EXCLUIDAS_STOCK_EQUIPOS = frozenset({'013-NC', '000', '013'})

SEMAFORO_META = {
    'SOBRESTOCK': {'label': 'Sobrestock (> 12 m)', 'color': 'red'},
    'PRECAUCION': {'label': 'Precaución (6 a 12 m)', 'color': 'amber'},
    'OPTIMO': {'label': 'Óptimo (3 a 6 m)', 'color': 'emerald'},
    'QUIEBRE': {'label': 'Baja Cobertura (< 3 m)', 'color': 'cyan'},
}

_STOPWORDS_MARCA = frozenset({
    'DE', 'LA', 'EL', 'EN', 'CON', 'SIN', 'PARA', 'DEL', 'LOS', 'LAS', 'POR', 'TIPO',
    'MODELO', 'AÑO', 'ANO', 'GRUA', 'GRÚA', 'ARTICULADA', 'CAMION', 'CAMIÓN', 'EQUIPO',
    'CARRO', 'BOMBA', 'ESTANQUE', 'ALJIBE', 'RECOLECTOR', 'CONTENEDOR', 'CAJA',
    'CARROCERIA', 'CARROCERÍA', 'REFRIGERADA', 'PICK', 'UP', 'TOLVA', 'GANCHO', 'CARGA',
    'ALZA', 'HOMBRES', 'LAVA', 'AISLADOR', 'DESOBSTRUCTOR', 'USADO', 'NUEVO', 'FULL',
    'MANUAL', 'AUTOMATICO', 'AUTOMÁTICO', 'HIDRAULICO', 'HIDRÁULICO', 'ELECTRICO',
    'ELÉCTRICO', 'MINI', 'SERIE', 'EVO', 'LTS', 'TON', 'MM', 'CM', 'HP', 'CV', 'KW',
    'KG', 'SOBRE', 'PLATAFORMA', 'SEMIREMOLQUE', 'REMOLQUE', 'AMBULANCIA', 'FURGON',
    'FURGÓN', 'CHASIS', 'CABINA', 'DOBLE', 'SIMPLE', 'BAJA', 'ALTA', 'PRESION',
    'PRESIÓN', 'AGUA', 'BARREDORA', 'COMPACTADOR', 'OPEN', 'TOP', 'SECA', 'ACERO',
    'APILABLE', 'EQUIPAMIENTO', 'MONTADO', 'MULTIPROPOSITO', 'BRAZO', 'HIDROELEVADOR',
    'PLUS', 'EURO', 'SKID', 'POLIBRAZO', 'ASPIRADOR', 'CILINDROS', 'RESCATE', 'UNIDAD',
    'PORTA', 'SISTEMA', 'KIT', 'MODULO', 'MÓDULO', 'TRUCK', 'CRANE', 'CARGO', 'VAN',
})

# Palabras compuestas / líneas de producto mapeadas a su marca fabricante oficial
_ALIASES_MARCA = {
    'BENZ': 'MERCEDES BENZ',
    'MERCEDES': 'MERCEDES BENZ',
    'CANTER': 'FUSO',
    'ATEGO': 'MERCEDES BENZ',
    'SPRINTER': 'MERCEDES BENZ',
    'ACTROS': 'MERCEDES BENZ',
    'CAMEL': 'SUPER PRODUCTS',
    'SUCKER': 'SUPER PRODUCTS',
    'SUPERSUCKER': 'SUPER PRODUCTS',
}

# Proveedores que son distribuidores multimarca (no usar su razón social como nombre de marca)
_PROVEEDORES_DISTRIBUIDORES = (
    'KAUFMANN', 'PORSCHE', 'PESCO', 'CURIFOR', 'ANDY OF MIAMI', 'MAKSAT',
    'CECOR', 'MOTORES DE LOS ANDES', 'CONTENAC', 'METALMECANICA', 'ICS SPA',
)

_FABRICANTES_PROVEEDOR = (
    ('SUPER PRODUCTS', 'SUPER PRODUCTS'),
    ('HIAB', 'HIAB'),
    ('USIMECA', 'USIMECA'),
    ('ALTEC', 'ALTEC'),
    ('ROSENBAUER', 'ROSENBAUER'),
    ('NLB', 'NLB'),
    ('VOLVO', 'VOLVO'),
    ('CARRYMAN', 'CARRYMAN'),
    ('AXION', 'AXION'),
    ('EFFER', 'EFFER'),
    ('ING INDUSTRIA', 'ING'),
    ('HEIL', 'HEIL'),
    ('PIOS', 'PIOS'),
    ('PİOS', 'PIOS'),
    ('PEERLESS', 'PEERLESS'),
    ('FREIGHTLINER', 'FREIGHTLINER'),
    ('DAIMLER', 'FREIGHTLINER'),
)


@dataclass(frozen=True)
class ClaveModelo:
    """Identificador compuesto sin colisiones entre marcas SAP."""
    familia: str
    subfamilia: str
    modelo: str

    def to_key(self) -> str:
        return f'{self.familia}|{self.subfamilia}|{self.modelo}'

    @classmethod
    def parse(cls, raw: str) -> 'ClaveModelo | None':
        parts = (raw or '').split('|')
        if len(parts) == 3:
            return cls(parts[0].strip(), parts[1].strip(), parts[2].strip())
        return None


# ── 2. Funciones puras de negocio (sin acceso a BD) ──────────────────────────

def es_bodega_stock_equipo(wh_code: str) -> bool:
    """True si la bodega suma a Stock Físico de Equipos (excluye NC, 000 y tránsitos T*)."""
    code = (wh_code or '').strip().upper()
    if not code or code in BODEGAS_EXCLUIDAS_STOCK_EQUIPOS:
        return False
    return not (code.startswith('T') or code.startswith('000'))


def clasificar_origen_sku(code: str, description: str) -> tuple[str, str]:
    """Infiere si un SKU de equipo es de Venta (sobre camión / armado) o Compra (equipo base)."""
    desc_up = (description or '').upper()
    cod = (code or '').strip()
    if cod.startswith('70') or 'S/CAMION' in desc_up or 'SOBRE CAMION' in desc_up or 'MONTAD' in desc_up:
        return 'Venta', 'Sí'
    return 'Compra', 'No'


def restar_meses(fecha: datetime.date, meses: int) -> datetime.date:
    y, m = fecha.year, fecha.month - meses
    while m <= 0:
        m += 12
        y -= 1
    return datetime.date(y, m, 1)


def calcular_cobertura_meses(inv_libre: int, ritmo_mensual: float) -> float:
    if ritmo_mensual > 0:
        return round(inv_libre / ritmo_mensual, 1)
    return COBERTURA_SIN_VENTA if inv_libre > 0 else 0.0


def evaluar_semaforo(cobertura_meses: float) -> tuple[str, str, str]:
    """Devuelve (codigo, etiqueta, color) según la política estándar de cobertura."""
    if cobertura_meses > UMBRAL_SOBRESTOCK_MESES:
        code = 'SOBRESTOCK'
    elif cobertura_meses >= UMBRAL_PRECAUCION_MESES:
        code = 'PRECAUCION'
    elif cobertura_meses >= UMBRAL_OPTIMO_MESES:
        code = 'OPTIMO'
    else:
        code = 'QUIEBRE'
    meta = SEMAFORO_META[code]
    return code, meta['label'], meta['color']


def inferir_nombre_marca(
    subfamilia: str,
    descripciones: list[str],
    proveedores: Counter | None = None,
) -> str:
    """Deriva el nombre comercial de la marca (`subfamilia` SAP) combinando Proveedor SAP y descripciones."""
    if not subfamilia:
        return 'Sin Marca (SAP)'

    # 1. Si el proveedor preferido en SAP identifica directamente al fabricante (ej. SUPER PRODUCTS LLC)
    if proveedores:
        top_prov = proveedores.most_common(1)[0][0].upper()
        if not any(d in top_prov for d in _PROVEEDORES_DISTRIBUIDORES):
            for patron, marca_oficial in _FABRICANTES_PROVEEDOR:
                if patron in top_prov:
                    return marca_oficial

    # 2. Inferencia desde descripciones de los SKUs
    tokens = Counter()
    for desc in descripciones:
        for w in re.findall(r'[A-ZÁÉÍÓÚÑ]{3,}', (desc or '').upper()):
            if w not in _STOPWORDS_MARCA:
                tokens[_ALIASES_MARCA.get(w, w)] += 1
    if not tokens:
        return f'Marca {subfamilia}'
    return tokens.most_common(1)[0][0]


def consolidar_modelos(modelos: list[dict[str, Any]], alcance_label: str = '') -> dict[str, Any]:
    """Combina dinámicamente 1, varios o todos los modelos SAP en una única radiografía S&OP."""
    if not modelos:
        return {}
    if len(modelos) == 1:
        base = dict(modelos[0])
        base['es_multimodelo'] = False
        base['es_consolidado_total'] = False
        base['modelos_claves'] = [base['clave']]
        base['modelos_codigos'] = [base['modelo']]
        base['skus'] = list(base.get('skus', []))
        return base

    principal = modelos[0]
    stk = sum(int(m['stock_cant']) for m in modelos)
    tr_r = sum(int(m['tr_real_cant']) for m in modelos)
    tr_p = sum(int(m['tr_proj_cant']) for m in modelos)
    prod = sum(int(m['en_proceso_cant']) for m in modelos)
    inv_ini = sum(int(m['inv_inicial_cant']) for m in modelos)
    bklg = sum(int(m['backlog_cant']) for m in modelos)
    inv_libre = sum(int(m['inv_libre_cant']) for m in modelos)
    e12 = sum(int(m['ent_12m_cant']) for m in modelos)
    ppto = sum(int(m['presup_cant']) for m in modelos)

    ritmo = round(max(e12 / 12.0 if e12 > 0 else 0.0, ppto / 12.0 if ppto > 0 else 0.0), 2)
    cob = calcular_cobertura_meses(inv_libre, ritmo)
    sem_code, sem_label, sem_color = evaluar_semaforo(cob)

    # Costo de compra: priorizar el del modelo principal (el que se va a comprar), respaldo promedio positivo
    costo_u = float(principal['costo_unitario_compra'] or 0)
    if costo_u <= 0:
        validos = [float(m['costo_unitario_compra']) for m in modelos if float(m['costo_unitario_compra'] or 0) > 0]
        costo_u = round(sum(validos) / len(validos), 2) if validos else 0.0

    codigos = [m['modelo'] for m in modelos]
    marcas = sorted({m['marca_label'] for m in modelos})

    es_global = len(modelos) > 4
    if es_global:
        m_label = alcance_label or (' / '.join(marcas[:3]) + '...' if len(marcas) > 3 else ' / '.join(marcas))
        mod_label = f"Consolidado Total ({len(modelos)} modelos)"
        nombre_label = f"Consolidado S&OP Global ({len(modelos)} modelos de {m_label})"
        clave_rep = 'TODOS'
    else:
        m_label = ' / '.join(marcas)
        mod_label = ' + '.join(codigos)
        nombre_label = f"Consolidado ({len(modelos)} modelos): {principal['nombre']}"
        clave_rep = ','.join(m['clave'] for m in modelos)

    # Consolidar SKUs únicos de todos los modelos preservando el orden
    skus_combinados = []
    vistos_sku = set()
    for m in modelos:
        for s in m.get('skus', []):
            if s['codigo'] not in vistos_sku:
                vistos_sku.add(s['codigo'])
                skus_combinados.append(s)

    return {
        'clave': clave_rep,
        'clave_principal': principal['clave'],
        'es_multimodelo': True,
        'es_consolidado_total': es_global,
        'modelos_claves': [m['clave'] for m in modelos],
        'modelos_codigos': codigos,
        'modelo': mod_label,
        'modelo_principal': principal['modelo'],
        'familia': principal['familia'],
        'subfamilia_code': principal['subfamilia_code'],
        'marca_label': m_label,
        'grupo_sap': principal['grupo_sap'],
        'nombre': nombre_label,
        'stock_cant': stk,
        'tr_real_cant': tr_r,
        'tr_proj_cant': tr_p,
        'en_proceso_cant': prod,
        'inv_inicial_cant': inv_ini,
        'backlog_cant': bklg,
        'inv_libre_cant': inv_libre,
        'ent_12m_cant': e12,
        'presup_cant': ppto,
        'ritmo_mensual': ritmo,
        'cobertura_meses': cob,
        'semaforo': sem_code,
        'semaforo_label': sem_label,
        'semaforo_color': sem_color,
        'costo_unitario_compra': costo_u,
        'skus': skus_combinados,
    }


def evaluar_simulacion(sf: dict[str, Any], cantidad_solicitada: int) -> dict[str, Any]:
    """Regla única de simulación y dictamen comercial 1 a 1 (soporta 1 modelo o consolidado multimodelo)."""
    cant = max(0, int(cantidad_solicitada or 0))
    costo_u = float(sf['costo_unitario_compra'] or COSTO_FALLBACK_USD)
    inversion_usd = cant * costo_u

    inv_libre_actual = int(sf['inv_libre_cant'])
    inv_libre_proj = inv_libre_actual + cant
    ritmo = float(sf['ritmo_mensual'])
    cob_actual = float(sf['cobertura_meses'])
    cob_proj = calcular_cobertura_meses(inv_libre_proj, ritmo)

    tr_total = int(sf['tr_real_cant']) + int(sf['tr_proj_cant'])
    es_multi = bool(sf.get('es_multimodelo'))
    prefijo = 'El consolidado de modelos' if es_multi else 'El modelo'
    etiqueta_mod = f"{sf['nombre']} (Modelo SAP {sf['modelo']} · {sf['marca_label']})"

    if cant == 0:
        decision, color = 'NEUTRO', 'slate'
        veredicto = 'Sin solicitud adicional'
        argumento = (
            f"{prefijo} {etiqueta_mod} cuenta actualmente con {inv_libre_actual} unidades disponibles "
            f"({sf['stock_cant']} en stock, {tr_total} en tránsito y {sf['en_proceso_cant']} en taller, "
            f"descontando {sf['backlog_cant']} comprometidas en backlog). Cobertura actual: {cob_actual} meses."
        )
    elif cob_actual > UMBRAL_SOBRESTOCK_MESES:
        decision, color = 'REFUTAR', 'red'
        veredicto = '⛔ REFUTAR COMPRA (Sobrestock Severo)'
        argumento = (
            f"Rechazar solicitud. {prefijo} ya cuenta con {inv_libre_actual} unidades disponibles no comprometidas "
            f"({cob_actual} meses de cobertura al ritmo anual de {sf['ent_12m_cant']} unidades). "
            f"Comprar {cant} unidades adicionales inmovilizaría ${inversion_usd:,.0f} USD en capital de trabajo "
            f"y dispararía la cobertura a {cob_proj} meses ({round(cob_proj / 12.0, 1)} años). "
            f"Recomendación: Priorizar la venta de las unidades en stock ({sf['stock_cant']}) y en tránsito ({tr_total})."
        )
    elif cob_actual >= UMBRAL_PRECAUCION_MESES:
        decision, color = 'NEGOCIAR', 'amber'
        veredicto = '⚠️ NEGOCIAR REDUCCIÓN O POSTERGAR'
        argumento = (
            f"Ajustar o diferir compra. El inventario disponible actual ({inv_libre_actual} unidades) cubre {cob_actual} meses "
            f"de demanda, suficiente para cubrir el lead time de fábrica. Comprar {cant} unidades (${inversion_usd:,.0f} USD) "
            f"elevaría la cobertura a {cob_proj} meses. Recomendación: Si el cliente no tiene orden en firme firmada, "
            f"aplazar a la próxima ventana S&OP o reducir a máximo 1 unidad."
        )
    elif cob_proj <= UMBRAL_PRECAUCION_MESES:
        decision, color = 'APROBAR', 'emerald'
        veredicto = '✅ APROBAR COMPRA (Completamente Justificada)'
        argumento = (
            f"Aprobar compra de {cant} unidades (${inversion_usd:,.0f} USD). "
            f"El inventario disponible actual es de solo {inv_libre_actual} unidades con cobertura baja ({cob_actual} meses) "
            f"frente a una demanda de {ritmo} un/mes. La compra asegura suministro para los próximos {cob_proj} meses "
            f"manteniendo un nivel de inventario saludable."
        )
    else:
        decision, color = 'APROBAR_PARCIAL', 'amber'
        veredicto = '⚠️ APROBACIÓN PARCIAL (Reducir volumen)'
        cant_optima = max(1, int(round((UMBRAL_PRECAUCION_MESES * ritmo) - inv_libre_actual)))
        argumento = (
            f"La compra solicitada de {cant} unidades sobrepasa la cobertura óptima (alcanza {cob_proj} meses). "
            f"Se recomienda contra-ofertar la compra de {cant_optima} unidades (${cant_optima * costo_u:,.0f} USD) "
            f"para dejar la cobertura en un rango de ~6 meses."
        )

    return {
        'clave': sf['clave'],
        'clave_principal': sf.get('clave_principal', sf['clave']),
        'es_multimodelo': es_multi,
        'modelos_claves': sf.get('modelos_claves', [sf['clave']]),
        'modelos_codigos': sf.get('modelos_codigos', [sf['modelo']]),
        'subfamilia': sf.get('modelo_principal', sf['modelo']),
        'modelo_display': sf['modelo'],
        'familia': sf['familia'],
        'marca_code': sf['subfamilia_code'],
        'marca_label': sf['marca_label'],
        'nombre': sf['nombre'],
        'cantidad_solicitada': cant,
        'costo_unitario_usd': costo_u,
        'inversion_usd': inversion_usd,
        'inv_libre_actual': inv_libre_actual,
        'inv_libre_proyectado': inv_libre_proj,
        'cobertura_actual_meses': cob_actual,
        'cobertura_proyectada_meses': cob_proj,
        'decision': decision,
        'veredicto': veredicto,
        'color': color,
        'argumento': argumento,
        'consolidado': {
            'modelo': sf['modelo'],
            'marca_label': sf['marca_label'],
            'nombre': sf['nombre'],
            'stock_cant': int(sf['stock_cant']),
            'tr_real_cant': int(sf['tr_real_cant']),
            'tr_proj_cant': int(sf['tr_proj_cant']),
            'en_proceso_cant': int(sf['en_proceso_cant']),
            'inv_inicial_cant': int(sf['inv_inicial_cant']),
            'backlog_cant': int(sf['backlog_cant']),
            'inv_libre_cant': inv_libre_actual,
            'ent_12m_cant': int(sf['ent_12m_cant']),
            'ritmo_mensual': ritmo,
            'cobertura_meses': cob_actual,
            'semaforo': sf['semaforo'],
            'semaforo_label': sf['semaforo_label'],
            'costo_unitario_compra': costo_u,
            'skus': [
                {
                    'codigo': s['codigo'],
                    'descripcion': s['descripcion'],
                    'origen': s['origen'],
                    'costo_unitario': s['costo_unitario'],
                    'stock_cant': s['stock_cant'],
                    'tr_cant': s['tr_real_cant'] + s['tr_proj_cant'],
                    'prod_cant': s.get('prod_cant', 0),
                }
                for s in sf.get('skus', [])
            ],
        },
    }


# ── 3. Catálogo dinámico de filtros desde SAP (ProductSKU) ───────────────────

def _cargar_proveedores_por_subfamilia(todos_equipos: list[ProductSKU]) -> dict[str, Counter]:
    """Mapea subfamilia SAP -> Counter de nombres de proveedor preferido (2 queries en lote)."""
    codes = [p.code for p in todos_equipos]
    pc_map = dict(ParametroCompra.objects.filter(product_id__in=codes).values_list('product_id', 'proveedor_preferido'))
    prov_codes = {v for v in pc_map.values() if v}
    prov_names = dict(Proveedor.objects.filter(codigo__in=prov_codes).values_list('codigo', 'nombre'))

    by_sub: dict[str, Counter] = defaultdict(Counter)
    for p in todos_equipos:
        sub = (p.subfamilia or '').strip()
        p_cod = pc_map.get(p.code, '')
        p_nom = prov_names.get(p_cod, '')
        if sub and p_nom:
            by_sub[sub][p_nom] += 1
    return by_sub


def _construir_catalogo_filtros(
    todos_equipos: list[ProductSKU],
    marca_label_global: dict[str, str],
    grupo_sel: str = '',
) -> dict[str, Any]:
    """Construye opciones de Grupo SAP y Marca (subfamilia SAP) ordenadas alfabéticamente."""
    grupos_counter = Counter()
    grupos_nombres = {}
    marcas_counter = Counter()

    for p in todos_equipos:
        g_code = (p.sap_group_code or '').strip()
        g_name = (p.sap_group_name or '').strip() or f'Grupo {g_code or "Sin Grupo"}'
        if g_code:
            grupos_counter[g_code] += 1
            grupos_nombres[g_code] = g_name

        if grupo_sel and g_code != grupo_sel:
            continue
        sub = (p.subfamilia or '').strip()
        if sub:
            marcas_counter[sub] += 1

    grupos = sorted(
        [{'code': code, 'name': grupos_nombres[code], 'count': cnt} for code, cnt in grupos_counter.items()],
        key=lambda g: g['name'].upper(),
    )

    marcas = sorted(
        [
            {
                'code': sub,
                'name': marca_label_global.get(sub, f'Marca {sub}'),
                'label': f"{marca_label_global.get(sub, f'Marca {sub}')} ({sub})",
                'count': cnt,
            }
            for sub, cnt in marcas_counter.items()
        ],
        key=lambda m: (m['name'].upper(), m['code']),
    )

    return {
        'grupos': grupos,
        'marcas': marcas,
        'grupos_map': grupos_nombres,
        'marcas_map': marca_label_global,
    }


# ── 4. Capa de carga en lote desde BD Datalake (cero N+1) ────────────────────

def _cargar_fuentes_bd(sku_codes: list[str], sku_map: dict[str, ProductSKU], hoy: datetime.date) -> dict[str, Any]:
    """Carga en bloque Stock, Tránsito/Taller, Backlog PC, Ventas L12M/YTD, Presupuesto y Decisiones."""
    # Stock Físico por SKU y bodega
    stock_by_sku = defaultdict(int)
    stock_bodegas_by_sku = defaultdict(lambda: defaultdict(int))
    for cod, bod, qty in StockActual.objects.filter(
        codigo__in=sku_codes, stock_disponible__gt=0
    ).values_list('codigo', 'bodega', 'stock_disponible'):
        if es_bodega_stock_equipo(bod):
            q_int = int(round(qty or 0))
            stock_by_sku[cod] += q_int
            stock_bodegas_by_sku[cod][bod] += q_int

    # Tránsito Real (FR), Tránsito Proyectado (OC) y Taller/Montaje (OF)
    tr_real = defaultdict(int)
    tr_proj = defaultdict(int)
    en_prod = defaultdict(int)
    for cod, tipo, qty in OCAbierta.objects.filter(
        product_id__in=sku_codes, cuenta=True, cantidad_pendiente__gt=0
    ).values_list('product_id', 'tipo_documento', 'cantidad_pendiente'):
        q_int = int(round(qty or 0))
        if tipo == OCAbierta.FR:
            tr_real[cod] += q_int
        elif tipo == OCAbierta.OC:
            tr_proj[cod] += q_int
        elif tipo == OCAbierta.OF:
            en_prod[cod] += q_int

    # Backlog Clientes (PC abiertos recientes <= MESES_BACKLOG_VIGENTE)
    corte_backlog = restar_meses(hoy, MESES_BACKLOG_VIGENTE)
    backlog_by_sku = defaultdict(int)
    backlog_usd_by_sku = defaultdict(float)
    backlog_items_by_sku = defaultdict(list)
    backlog_antiguos = 0

    for cd in CompromisoDetalle.objects.filter(
        codigo_sku__in=sku_codes, tipo='PC', cantidad__gt=0
    ).order_by('-fecha_emision'):
        if cd.fecha_emision and cd.fecha_emision < corte_backlog:
            backlog_antiguos += 1
            continue
        q_int = int(round(cd.cantidad or 0))
        sku_obj = sku_map.get(cd.codigo_sku)
        costo_u = float(cd.costo_unitario or (sku_obj.unit_cost_usd if sku_obj else 0) or 0)
        tot_usd = q_int * costo_u
        backlog_by_sku[cd.codigo_sku] += q_int
        backlog_usd_by_sku[cd.codigo_sku] += tot_usd
        backlog_items_by_sku[cd.codigo_sku].append({
            'codigo': cd.codigo_sku,
            'descripcion': sku_obj.description if sku_obj else '',
            'cantidad': q_int,
            'costo_unitario': costo_u,
            'total_usd': tot_usd,
            'ejecutivo': cd.responsable or 'Sin asignar',
            'pc': cd.numero,
            'cliente': cd.nombre_cliente or cd.codigo_cliente or 'Cliente Directo',
            'fecha_emision': cd.fecha_emision.strftime('%d-%m-%Y') if cd.fecha_emision else '',
        })

    # Ventas / Entregas L12M y YTD
    ult_mes = ConsumoMensual.objects.order_by('-mes').values_list('mes', flat=True).first()
    ent_12m, ent_ytd = defaultdict(int), defaultdict(int)
    ent_12m_usd, ent_ytd_usd = defaultdict(float), defaultdict(float)

    if ult_mes:
        desde_12m = restar_meses(ult_mes, 12)
        inicio_anio = datetime.date(ult_mes.year, 1, 1)
        anio_ref = ult_mes.year

        for r in ConsumoMensual.objects.filter(
            product_id__in=sku_codes, origen=ConsumoMensual.VENTA, mes__gt=desde_12m
        ).values('product_id').annotate(q=Sum('cantidad')):
            ent_12m[r['product_id']] = int(round(r['q'] or 0))

        for r in ConsumoMensual.objects.filter(
            product_id__in=sku_codes, origen=ConsumoMensual.VENTA, mes__gte=inicio_anio
        ).values('product_id').annotate(q=Sum('cantidad')):
            ent_ytd[r['product_id']] = int(round(r['q'] or 0))

        for r in VentaMensual.objects.filter(
            product_id__in=sku_codes, mes__gt=desde_12m
        ).values('product_id').annotate(m=Sum('monto_usd')):
            ent_12m_usd[r['product_id']] = float(r['m'] or 0)

        for r in VentaMensual.objects.filter(
            product_id__in=sku_codes, mes__gte=inicio_anio
        ).values('product_id').annotate(m=Sum('monto_usd')):
            ent_ytd_usd[r['product_id']] = float(r['m'] or 0)
    else:
        anio_ref = hoy.year

    # Presupuesto anual por ClaveModelo (familia|subfamilia|modelo)
    presup_by_key = {
        ClaveModelo(p.familia, p.subfamilia, p.modelo).to_key(): {
            'cantidad': int(round(p.cantidad)),
            'monto_usd': float(p.monto_usd),
        }
        for p in PresupuestoSOP.objects.filter(anio=anio_ref)
    }

    return {
        'anio_ref': anio_ref,
        'ultimo_mes_consumo': ult_mes,
        'stock': stock_by_sku,
        'stock_bodegas': stock_bodegas_by_sku,
        'tr_real': tr_real,
        'tr_proj': tr_proj,
        'en_prod': en_prod,
        'backlog': backlog_by_sku,
        'backlog_usd': backlog_usd_by_sku,
        'backlog_items': backlog_items_by_sku,
        'backlog_antiguos': backlog_antiguos,
        'ent_12m': ent_12m,
        'ent_ytd': ent_ytd,
        'ent_12m_usd': ent_12m_usd,
        'ent_ytd_usd': ent_ytd_usd,
        'presupuesto': presup_by_key,
    }


# ── 5. Servicio principal de consulta S&OP Equipos ───────────────────────────

def get_sop_equipos_data(
    grupo: str = '',
    marca: str = '',
    solo_con_actividad: bool = True,
) -> dict[str, Any]:
    """Construye la radiografía S&OP de Equipos (Todas las Marcas o filtrada por Grupo/Marca SAP)."""
    hoy = timezone.localdate()
    grupo = (grupo or '').strip()
    marca = (marca or '').strip()

    todos_equipos = list(
        ProductSKU.objects.filter(is_active=True, clase=CLASE_EQUIPOS).order_by('sap_group_name', 'subfamilia', 'modelo', 'code')
    )
    if not todos_equipos:
        return {
            'hay_datos': False,
            'error': 'No se encontraron equipos (clase=1) en ProductSKU. Ejecute primero la sincronización del Datalake.',
        }

    # Mapa global de nombres de marca usando Proveedor SAP + descripciones (ej. 05 -> SUPER PRODUCTS)
    prov_por_sub = _cargar_proveedores_por_subfamilia(todos_equipos)
    todas_descs = defaultdict(list)
    for p in todos_equipos:
        sub = (p.subfamilia or '').strip()
        if sub:
            todas_descs[sub].append(p.description or '')
    marca_label_global = {
        sub: inferir_nombre_marca(sub, ds, prov_por_sub.get(sub))
        for sub, ds in todas_descs.items()
    }
    catalogo = _construir_catalogo_filtros(todos_equipos, marca_label_global, grupo_sel=grupo)

    # Aplicar filtro de alcance (Grupo SAP y/o Marca/Subfamilia SAP)
    skus_alcance = [
        p for p in todos_equipos
        if (not grupo or (p.sap_group_code or '').strip() == grupo)
        and (not marca or (p.subfamilia or '').strip() == marca)
    ]

    ultima_carga = CargaDatos.objects.order_by('-cargado_en').first()
    fecha_sync = ultima_carga.cargado_en if ultima_carga else None

    if not skus_alcance:
        return {
            'hay_datos': True,
            'fuente': 'BD Datalake (SAP)',
            'fecha_sync': fecha_sync,
            'anio_ref': hoy.year,
            'catalogo': catalogo,
            'f_grupo': grupo,
            'f_marca': marca,
            'alcance_label': 'Sin equipos en el filtro seleccionado',
            'skus_sin_modelo': [],
            'backlog_antiguos_excluidos': 0,
            'kpis': _kpis_vacios(),
            'subfamilias': [],
            'subfamilias_dict': {},
            'skus_detalle': [],
            'propuestas_recientes': [],
            'total_skus': 0,
            'total_subfamilias': 0,
        }

    sku_codes = [p.code for p in skus_alcance]
    sku_map = {p.code: p for p in skus_alcance}
    fuentes = _cargar_fuentes_bd(sku_codes, sku_map, hoy)

    # Propuestas / Decisiones 1 a 1 filtradas por alcance actual
    familias_alcance = {(p.familia or '').strip() for p in skus_alcance}
    subfamilias_alcance = {(p.subfamilia or '').strip() for p in skus_alcance}
    propuestas_qs = PropuestaCompraSOP.objects.select_related('creado_por', 'solicitud_compra')
    if marca:
        propuestas_qs = propuestas_qs.filter(subfamilia=marca)
    elif grupo:
        propuestas_qs = propuestas_qs.filter(familia__in=familias_alcance, subfamilia__in=subfamilias_alcance)
    propuestas_recientes = list(propuestas_qs[:100])

    solic_by_key = defaultdict(list)
    for pr in propuestas_recientes:
        k_pr = ClaveModelo(pr.familia, pr.subfamilia, pr.modelo).to_key()
        solic_by_key[k_pr].append({
            'id': pr.id,
            'modelo': pr.modelo,
            'vendedor': pr.vendedor,
            'negocio': pr.negocio or 'Propuesta comercial',
            'descripcion': pr.comentario or pr.get_decision_display(),
            'cantidad': pr.cantidad_aprobada if pr.decision in (PropuestaCompraSOP.APROBADA, PropuestaCompraSOP.PARCIAL) else pr.cantidad_solicitada,
            'cantidad_solicitada': pr.cantidad_solicitada,
            'cantidad_aprobada': pr.cantidad_aprobada,
            'total_usd': pr.inversion_usd,
            'decision': pr.decision,
            'decision_label': pr.get_decision_display(),
            'fecha': pr.creado_en.strftime('%d-%m-%Y %H:%M'),
        })

    # Agregación por Modelo SAP (clave compuesta familia|subfamilia|modelo)
    skus_detalle = []
    modelos_map: dict[str, dict[str, Any]] = {}
    skus_sin_modelo = []

    for idx, p in enumerate(skus_alcance, start=1):
        fam = (p.familia or '').strip()
        sub = (p.subfamilia or '').strip()
        mod = (p.modelo or '').strip()
        grp_name = (p.sap_group_name or '').strip() or 'Equipos'
        m_label = marca_label_global.get(sub, f'Marca {sub}' if sub else 'Sin Marca')

        if not mod:
            skus_sin_modelo.append({
                'codigo': p.code,
                'descripcion': p.description,
                'grupo': grp_name,
                'familia': fam,
                'subfamilia': sub,
                'marca': m_label,
            })
            mod_key = 'SIN_MODELO'
        else:
            mod_key = mod

        clave_compuesta = ClaveModelo(fam, sub, mod_key).to_key()

        origen, sobre_camion = clasificar_origen_sku(p.code, p.description)
        costo_u = float(p.unit_cost_usd or 0)
        stk_c = fuentes['stock'].get(p.code, 0)
        tr_r = fuentes['tr_real'].get(p.code, 0)
        tr_p = fuentes['tr_proj'].get(p.code, 0)
        prod_c = fuentes['en_prod'].get(p.code, 0)
        bklg_c = fuentes['backlog'].get(p.code, 0)
        e12_c = fuentes['ent_12m'].get(p.code, 0)
        eytd_c = fuentes['ent_ytd'].get(p.code, 0)

        tiene_actividad = any((stk_c, tr_r, tr_p, prod_c, bklg_c, e12_c, eytd_c))
        if (
            solo_con_actividad
            and not tiene_actividad
            and clave_compuesta not in fuentes['presupuesto']
            and clave_compuesta not in solic_by_key
        ):
            continue

        stk_usd = stk_c * costo_u
        tr_r_usd = tr_r * costo_u
        tr_p_usd = tr_p * costo_u
        prod_usd = prod_c * costo_u
        bklg_usd = fuentes['backlog_usd'].get(p.code, bklg_c * costo_u)
        e12_usd = fuentes['ent_12m_usd'].get(p.code) or (e12_c * costo_u)
        eytd_usd = fuentes['ent_ytd_usd'].get(p.code) or (eytd_c * costo_u)

        sku_item = {
            'fila': idx,
            'codigo': p.code,
            'origen': origen,
            'grupo_sap': grp_name,
            'familia': fam,
            'subfamilia': mod_key,
            'marca_code': sub,
            'marca_label': m_label,
            'descripcion': p.description,
            'sobre_camion': sobre_camion,
            'costo_unitario': costo_u,
            'stock_cant': stk_c,
            'stock_usd': stk_usd,
            'stock_bodegas': dict(fuentes['stock_bodegas'].get(p.code, {})),
            'tr_real_cant': tr_r,
            'tr_real_usd': tr_r_usd,
            'tr_proj_cant': tr_p,
            'tr_proj_usd': tr_p_usd,
            'prod_cant': prod_c,
            'prod_usd': prod_usd,
            'solic_cant': 0,
            'solic_usd': 0.0,
            'backlog_cant': bklg_c,
            'backlog_usd': bklg_usd,
            'ent_2026_cant': eytd_c,
            'ent_2026_usd': eytd_usd,
            'presup_cant': 0,
            'presup_usd': 0.0,
            'ent_12m_cant': e12_c,
            'ent_12m_usd': e12_usd,
        }
        skus_detalle.append(sku_item)

        if clave_compuesta not in modelos_map:
            ppto = fuentes['presupuesto'].get(clave_compuesta, {'cantidad': 0, 'monto_usd': 0.0})
            modelos_map[clave_compuesta] = {
                'clave': clave_compuesta,
                'dom_id': re.sub(r'[^A-Za-z0-9_-]', '_', clave_compuesta),
                'modelo': mod_key,
                'familia': fam,
                'subfamilia_code': sub,
                'marca_label': m_label,
                'grupo_sap': grp_name,
                'nombre': 'Sin Modelo asignado en SAP (revisar Master Data)' if mod_key == 'SIN_MODELO' else p.description,
                'skus': [],
                'stock_cant': 0,
                'stock_usd': 0.0,
                'tr_real_cant': 0,
                'tr_real_usd': 0.0,
                'tr_proj_cant': 0,
                'tr_proj_usd': 0.0,
                'en_proceso_cant': 0,
                'en_proceso_usd': 0.0,
                'solic_cant': 0,
                'solic_usd': 0.0,
                'backlog_cant': 0,
                'backlog_usd': 0.0,
                'ent_2026_cant': 0,
                'ent_2026_usd': 0.0,
                'presup_cant': ppto['cantidad'],
                'presup_usd': ppto['monto_usd'],
                'ent_12m_cant': 0,
                'ent_12m_usd': 0.0,
                'backlog_items': [],
                'solicitudes_items': list(solic_by_key.get(clave_compuesta, [])),
                'costo_unitario_compra': 0.0,
            }

        sf = modelos_map[clave_compuesta]
        sf['skus'].append(sku_item)

        if mod_key != 'SIN_MODELO' and origen == 'Compra':
            if sf['costo_unitario_compra'] == 0 or costo_u > sf['costo_unitario_compra']:
                sf['nombre'] = p.description
                sf['costo_unitario_compra'] = costo_u

        sf['stock_cant'] += stk_c
        sf['stock_usd'] += stk_usd
        sf['tr_real_cant'] += tr_r
        sf['tr_real_usd'] += tr_r_usd
        sf['tr_proj_cant'] += tr_p
        sf['tr_proj_usd'] += tr_p_usd
        sf['en_proceso_cant'] += prod_c
        sf['en_proceso_usd'] += prod_usd
        sf['backlog_cant'] += bklg_c
        sf['backlog_usd'] += bklg_usd
        sf['ent_2026_cant'] += eytd_c
        sf['ent_2026_usd'] += eytd_usd
        sf['ent_12m_cant'] += e12_c
        sf['ent_12m_usd'] += e12_usd
        sf['backlog_items'].extend(fuentes['backlog_items'].get(p.code, []))

    # Cálculo de métricas derivadas y KPIs macro
    subfamilias_list = []
    tot = defaultdict(float)

    for sf in modelos_map.values():
        if sf['costo_unitario_compra'] <= 0:
            costos_validos = [s['costo_unitario'] for s in sf['skus'] if s['costo_unitario'] > 0]
            sf['costo_unitario_compra'] = round(sum(costos_validos) / len(costos_validos), 2) if costos_validos else 0.0

        for sol in sf['solicitudes_items']:
            if sol['decision'] in (PropuestaCompraSOP.PENDIENTE, PropuestaCompraSOP.APROBADA, PropuestaCompraSOP.PARCIAL):
                sf['solic_cant'] += sol['cantidad']
                sf['solic_usd'] += sol['total_usd']

        sf['inv_inicial_cant'] = sf['stock_cant'] + sf['tr_real_cant'] + sf['tr_proj_cant'] + sf['en_proceso_cant']
        sf['inv_inicial_usd'] = sf['stock_usd'] + sf['tr_real_usd'] + sf['tr_proj_usd'] + sf['en_proceso_usd']
        sf['inv_libre_cant'] = sf['inv_inicial_cant'] - sf['backlog_cant']
        sf['inv_libre_usd'] = sf['inv_inicial_usd'] - sf['backlog_usd']

        ritmo = max(
            sf['ent_12m_cant'] / 12.0 if sf['ent_12m_cant'] > 0 else 0.0,
            sf['presup_cant'] / 12.0 if sf['presup_cant'] > 0 else 0.0,
        )
        sf['ritmo_mensual'] = round(ritmo, 2)
        sf['cobertura_meses'] = calcular_cobertura_meses(sf['inv_libre_cant'], sf['ritmo_mensual'])
        sf['semaforo'], sf['semaforo_label'], sf['semaforo_color'] = evaluar_semaforo(sf['cobertura_meses'])

        subfamilias_list.append(sf)

        for field in (
            'stock_cant', 'stock_usd', 'tr_real_cant', 'tr_real_usd', 'tr_proj_cant', 'tr_proj_usd',
            'en_proceso_cant', 'en_proceso_usd', 'backlog_cant', 'backlog_usd',
            'ent_12m_cant', 'ent_12m_usd', 'ent_2026_cant', 'ent_2026_usd',
            'presup_cant', 'presup_usd', 'solic_cant', 'solic_usd',
        ):
            tot[field] += sf[field]

        # Para el % de cumplimiento, comparar solo contra los modelos que SÍ tienen presupuesto cargado
        if sf['presup_cant'] > 0:
            tot['avance_ppto_cant'] += sf['ent_2026_cant'] + sf['backlog_cant']
            tot['modelos_con_ppto'] += 1
        if sf['presup_usd'] > 0:
            tot['avance_ppto_usd'] += sf['ent_2026_usd'] + sf['backlog_usd']

    tot['modelos_totales'] = len(subfamilias_list)
    subfamilias_list.sort(key=lambda x: (-x['ent_12m_cant'], -x['inv_libre_cant'], x['marca_label'], x['modelo']))

    kpis = _construir_kpis_macro(tot)

    # Etiqueta legible del alcance activo
    partes_alcance = []
    if grupo:
        partes_alcance.append(catalogo['grupos_map'].get(grupo, f'Grupo {grupo}'))
    if marca:
        partes_alcance.append(f"{marca_label_global.get(marca, f'Marca {marca}')} ({marca})")
    alcance_label = ' · '.join(partes_alcance) if partes_alcance else 'Todas las Marcas y Grupos de Equipos'

    # Índice de búsqueda rápida por clave compuesta y también por código de modelo simple
    by_key = {sf['clave']: sf for sf in subfamilias_list}
    by_modelo_simple = {}
    for sf in subfamilias_list:
        by_modelo_simple.setdefault(sf['modelo'], sf)

    return {
        'hay_datos': True,
        'fuente': 'BD Datalake (SAP)',
        'fecha_sync': fecha_sync,
        'anio_ref': fuentes['anio_ref'],
        'ultimo_mes_consumo': fuentes['ultimo_mes_consumo'],
        'catalogo': catalogo,
        'f_grupo': grupo,
        'f_marca': marca,
        'alcance_label': alcance_label,
        'backlog_antiguos_excluidos': fuentes['backlog_antiguos'],
        'skus_sin_modelo': skus_sin_modelo,
        'kpis': kpis,
        'subfamilias': subfamilias_list,
        'subfamilias_dict': by_key,
        'subfamilias_by_modelo': by_modelo_simple,
        'skus_detalle': skus_detalle,
        'propuestas_recientes': propuestas_recientes,
        'total_skus': len(skus_detalle),
        'total_subfamilias': len(subfamilias_list),
    }


def _kpis_vacios() -> dict[str, Any]:
    return _construir_kpis_macro(defaultdict(float))


def _construir_kpis_macro(tot: dict[str, float]) -> dict[str, Any]:
    inv_ini_c = int(tot['stock_cant'] + tot['tr_real_cant'] + tot['tr_proj_cant'] + tot['en_proceso_cant'])
    inv_ini_u = tot['stock_usd'] + tot['tr_real_usd'] + tot['tr_proj_usd'] + tot['en_proceso_usd']
    inv_fin_c = inv_ini_c - int(tot['backlog_cant'])
    inv_fin_u = inv_ini_u - tot['backlog_usd']
    inv_proj_c = inv_fin_c + int(tot['solic_cant'])
    inv_proj_u = inv_fin_u + tot['solic_usd']

    # Fórmula gerencial estándar: Inventario Disponible / ((Entregado L12M + Backlog) / 12)
    demanda_anual_macro = tot['ent_12m_cant'] + tot['backlog_cant']
    ritmo_macro = (demanda_anual_macro / 12.0) if demanda_anual_macro > 0 else 0.0
    rot_actual = round(inv_fin_c / ritmo_macro, 2) if ritmo_macro > 0 else 0.0
    rot_proj = round(inv_proj_c / ritmo_macro, 2) if ritmo_macro > 0 else 0.0

    # Cumplimiento calculado estrictamente sobre modelos con presupuesto cargado (evita inflar % en Todas las Marcas)
    avance_ppto_c = int(tot['avance_ppto_cant'])
    avance_ppto_u = tot['avance_ppto_usd']
    cump_cant = round((avance_ppto_c / tot['presup_cant']) * 100.0, 2) if tot['presup_cant'] > 0 else 0.0
    cump_usd = round((avance_ppto_u / tot['presup_usd']) * 100.0, 2) if tot['presup_usd'] > 0 else 0.0

    tiene_presupuesto = tot['presup_cant'] > 0 or tot['presup_usd'] > 0
    avance_cant = int(tot['ent_2026_cant'] + tot['backlog_cant'])
    avance_usd = tot['ent_2026_usd'] + tot['backlog_usd']
    modelos_tot = int(tot.get('modelos_totales', 0))
    modelos_ppto = int(tot.get('modelos_con_ppto', 0))
    ppto_parcial = bool(tiene_presupuesto and 0 < modelos_ppto < modelos_tot)

    return {
        'entregado_12m_usd': tot['ent_12m_usd'],
        'entregado_12m_cant': int(tot['ent_12m_cant']),
        'entregado_2026_usd': tot['ent_2026_usd'],
        'entregado_2026_cant': int(tot['ent_2026_cant']),
        'backlog_usd': tot['backlog_usd'],
        'backlog_cant': int(tot['backlog_cant']),
        'avance_2026_cant': avance_cant,
        'avance_2026_usd': avance_usd,
        'avance_ppto_cant': avance_ppto_c,
        'avance_ppto_usd': avance_ppto_u,
        'avance_con_ppto_cant': avance_ppto_c,
        'avance_con_ppto_usd': avance_ppto_u,
        'modelos_con_ppto': modelos_ppto,
        'modelos_totales': modelos_tot,
        'ppto_parcial': ppto_parcial,
        'presupuesto_usd': tot['presup_usd'],
        'presupuesto_cant': int(tot['presup_cant']),
        'tiene_presupuesto': tiene_presupuesto,
        'cumplimiento_cant_pct': cump_cant,
        'cumplimiento_usd_pct': cump_usd,
        'stock_usd': tot['stock_usd'],
        'stock_cant': int(tot['stock_cant']),
        'transito_real_usd': tot['tr_real_usd'],
        'transito_real_cant': int(tot['tr_real_cant']),
        'transito_proj_usd': tot['tr_proj_usd'],
        'transito_proj_cant': int(tot['tr_proj_cant']),
        'en_proceso_usd': tot['en_proceso_usd'],
        'en_proceso_cant': int(tot['en_proceso_cant']),
        'inventario_inicial_usd': inv_ini_u,
        'inventario_inicial_cant': inv_ini_c,
        'inventario_final_usd': inv_fin_u,
        'inventario_final_cant': inv_fin_c,
        'rotacion_actual_meses': rot_actual,
        'solicitud_usd': tot['solic_usd'],
        'solicitud_cant': int(tot['solic_cant']),
        'inv_final_proj_usd': inv_proj_u,
        'inv_final_proj_cant': inv_proj_c,
        'rotacion_proj_meses': rot_proj,
    }


def resolver_modelo(data: dict[str, Any], clave_o_modelo: str) -> dict[str, Any] | None:
    """Resuelve un modelo por clave compuesta `fam|sub|mod` o por código `modelo` simple."""
    raw = str(clave_o_modelo or '').strip()
    if not raw:
        return None
    return data['subfamilias_dict'].get(raw) or data.get('subfamilias_by_modelo', {}).get(raw)


def resolver_modelos_multi(data: dict[str, Any], claves_csv: str) -> list[dict[str, Any]]:
    """Resuelve 1 o varios modelos separados por coma preservando el orden y evitando duplicados."""
    vistos = set()
    resueltos = []
    for token in str(claves_csv or '').split(','):
        sf = resolver_modelo(data, token.strip())
        if sf and sf['clave'] not in vistos:
            vistos.add(sf['clave'])
            resueltos.append(sf)
    return resueltos


def simular_propuesta_compra(clave_o_modelo: str, cantidad_solicitada: int, grupo: str = '', marca: str = '') -> dict[str, Any]:
    """Simula 1 modelo, multimodelo (`k1,k2`) o consolidado de todas las marcas (`TODOS` o vacío)."""
    data = get_sop_equipos_data(grupo=grupo, marca=marca)
    if not data.get('hay_datos'):
        return {'error': 'No hay datos de Equipos cargados desde el Datalake'}

    raw = str(clave_o_modelo or '').strip().upper()
    if not raw or raw in ('TODOS', 'ALL', 'CONSOLIDADO', 'GLOBAL'):
        modelos = data['subfamilias']
    else:
        modelos = resolver_modelos_multi(data, clave_o_modelo)
        if not modelos:
            return {'error': f'Modelo SAP {clave_o_modelo} no encontrado'}

    sf_consolidado = consolidar_modelos(modelos, alcance_label=data.get('alcance_label', ''))
    return evaluar_simulacion(sf_consolidado, cantidad_solicitada)


@transaction.atomic
def generar_solicitud_compra_desde_propuesta(propuesta: PropuestaCompraSOP, usuario=None) -> SolicitudCompra:
    """Genera una SolicitudCompra + LineaSolicitud oficial desde una decisión aprobada en la Bitácora 1 a 1."""
    if propuesta.solicitud_compra_id:
        return propuesta.solicitud_compra

    cantidad = int(propuesta.cantidad_aprobada or 0)
    if cantidad <= 0 and int(propuesta.cantidad_solicitada or 0) > 0:
        cantidad = int(propuesta.cantidad_solicitada)
        propuesta.cantidad_aprobada = cantidad
        if propuesta.decision in (PropuestaCompraSOP.PENDIENTE, PropuestaCompraSOP.POSTERGADA):
            propuesta.decision = PropuestaCompraSOP.APROBADA
    if cantidad <= 0:
        raise ValueError('Solo se puede generar SC cuando la cantidad solicitada o aprobada es mayor a 0.')

    # Buscar el SKU de Compra principal del modelo SAP (preferir origen Compra con mayor costo)
    candidatos = list(ProductSKU.objects.filter(
        is_active=True, clase=CLASE_EQUIPOS,
        familia=propuesta.familia, subfamilia=propuesta.subfamilia, modelo=propuesta.modelo,
    ))
    if not candidatos:
        candidatos = list(ProductSKU.objects.filter(is_active=True, clase=CLASE_EQUIPOS, modelo=propuesta.modelo))
    if not candidatos:
        raise ValueError(f'No se encontró un SKU activo en SAP para el modelo {propuesta.modelo}.')

    compras = [p for p in candidatos if clasificar_origen_sku(p.code, p.description)[0] == 'Compra']
    pool = compras or candidatos
    sku = max(pool, key=lambda p: float(p.unit_cost_usd or 0))

    # Resolver proveedor preferido desde ParametroCompra o última OC abierta
    prov_code = (
        ParametroCompra.objects.filter(product=sku).values_list('proveedor_preferido', flat=True).first()
        or OCAbierta.objects.filter(product=sku).exclude(proveedor_codigo='').values_list('proveedor_codigo', flat=True).first()
        or ''
    )
    proveedor = Proveedor.objects.filter(codigo=prov_code).first() if prov_code else None

    hoy = timezone.localdate()
    precio_u = float(propuesta.costo_unitario_usd or sku.unit_cost_usd or 0)
    nota_parts = [f'Mesa S&OP Equipos 1 a 1 · Mod {propuesta.modelo}']
    if propuesta.negocio:
        nota_parts.append(f'Negocio: {propuesta.negocio}')
    if propuesta.vendedor:
        nota_parts.append(f'Vendedor: {propuesta.vendedor}')

    sc = SolicitudCompra.objects.create(
        proveedor=proveedor,
        bodega_entrega='013-06',
        tipo=SolicitudCompra.EXCEPCION,
        estado=SolicitudCompra.BORRADOR,
        fecha=hoy,
        creada_por=usuario,
        comentario=' | '.join(nota_parts)[:255],
    )
    LineaSolicitud.objects.create(
        solicitud=sc,
        product=sku,
        cantidad_sugerida=float(propuesta.cantidad_solicitada or cantidad),
        cantidad_final=float(cantidad),
        precio_unitario=precio_u,
        motivo=(propuesta.comentario or f'Aprobado en Mesa S&OP 1 a 1 ({propuesta.negocio or "Equipos"})')[:255],
        excepcion=True,
        causa_excepcion='SOP_EQUIPOS',
        urgencia='NORMAL',
    )
    propuesta.solicitud_compra = sc
    propuesta.save(update_fields=['solicitud_compra', 'cantidad_aprobada', 'decision', 'actualizado_en'])
    return sc
