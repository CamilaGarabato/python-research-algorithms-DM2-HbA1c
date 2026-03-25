### ESTE CÓDIGO DETECTA EL DIAGNÓSTICO DE DBT 2 EN LOS PDFs DE UNA CARPETA
# Requiere instalar pdfplumber: pip install pdfplumber

import os
import pdfplumber
import argparse
import sqlite3
import re
import unicodedata
from pathlib import Path
from datetime import datetime
import warnings

# =================== CONFIGURACIÓN DE PATHS ===================
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / ".." / "HC_2025.db"
CARPETA_PDFS = BASE_DIR / ".." / "Muestra"
DB_PATH = DB_PATH.resolve()
CARPETA_PDFS = CARPETA_PDFS.resolve()

# =================== SUPRIMIR WARNINGS ===================
warnings.filterwarnings("ignore", message="Could get FontBBox from font descriptor")
warnings.filterwarnings("ignore", category=UserWarning, module="pdfplumber")

# =================== CONFIGURACIÓN DE ARGUMENTOS ===================
parser = argparse.ArgumentParser(description='Detectar diagnósticos de DM2 en archivos PDF')
parser.add_argument('--mode', default='check', choices=['check', 'update-db'],
                    help='Modo de operación: check (solo verificar) o update-db (actualizar base de datos)')
parser.add_argument('--pdf-dir', default=str(CARPETA_PDFS),
                    help='Ruta alternativa a la carpeta de PDFs')
args = parser.parse_args()

if args.pdf_dir != str(CARPETA_PDFS):
    CARPETA_PDFS = Path(args.pdf_dir).resolve()

# =================== PATRONES POR ORDEN DE PRIORIDAD ===================
PATRONES_DM2_ALTA_PRIORIDAD = [
    "DBT2", "DM2", "T2DM", "DBT T2", "DM T2",
    "DBT TIPO 2", "DM TIPO 2", "DBT TIPO II", "DM TIPO II",
    "DIABETES TIPO 2", "DIABETES TIPO II", "DIABETES MELLITUS TIPO 2",
    "DIABETES MELLITUS TIPO II", "DIABETES 2", "DIABETES II"
]

PATRONES_DM2_MEDIA_PRIORIDAD = [
    "DIABETES MELLITUS NO INSULINODEPENDIENTE", "DMNID",
    "DIABETES DEL ADULTO", "DIABETES TARDÍA"
]

PATRONES_CIE10 = [
    "E11", "E11.9", "E119",
    "DIABETES MELLITUS INSULINODEPENDIENTE"
]

EXCLUSIONES_DM1 = [
    "DBT1", "DM1", "T1DM", "DBT TIPO 1", "DM TIPO 1", "DBT TIPO I", "DM TIPO I",
    "DIABETES TIPO 1", "DIABETES TIPO I", "E10", "E10.9", "E109"
]

# =================== FUNCIONES AUXILIARES ===================
def normalizar_texto(texto):
    """Normaliza texto para búsqueda sin distinción de mayúsculas/minúsculas y acentos"""
    if not texto:
        return ""
    texto = texto.upper()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) 
                   if unicodedata.category(c) != 'Mn')
    return texto


def encontrar_contexto_dm2(texto, patron_encontrado):
    """Encuentra el contexto alrededor del término DM2 encontrado"""
    texto_normalizado = normalizar_texto(texto)
    indice = texto_normalizado.find(patron_encontrado)
    
    if indice == -1:
        return "Contexto no disponible"
    
    inicio = max(0, indice - 100)
    fin = min(len(texto_normalizado), indice + len(patron_encontrado) + 100)
    contexto = texto_normalizado[inicio:fin].replace('\n', ' ').strip()
    
    if len(contexto) > 150:
        contexto = contexto[:150] + "..."
    return contexto


def contiene_dm2_priorizado(texto):
    """Busca DM2 por orden de prioridad, evitando falsos positivos"""
    texto_normalizado = normalizar_texto(texto)
    
    # PRIMERO: Excluir DM1 claramente identificado
    for exclusion in EXCLUSIONES_DM1:
        if exclusion in texto_normalizado:
            return None, "Excluido por DM1"
    
    # NIVEL 1: Buscar términos específicos de DM2 (alta prioridad)
    for patron in PATRONES_DM2_ALTA_PRIORIDAD:
        if patron in texto_normalizado:
            return patron, "Alta prioridad"
    
    # NIVEL 2: Buscar términos de DM2 (media prioridad)
    for patron in PATRONES_DM2_MEDIA_PRIORIDAD:
        if patron in texto_normalizado:
            return patron, "Media prioridad"
    
    # NIVEL 3: Buscar códigos CIE-10 (solo si no hay términos anteriores)
    cie10_encontrado = None
    for patron in PATRONES_CIE10:
        if patron in texto_normalizado:
            cie10_encontrado = patron
            break
    
    if cie10_encontrado:
        contexto_seguro = True
        indicios_dm1 = ["JUVENIL", "INFANTIL", "NIÑO", "PEDIATRICA", "INICIO PRECOZ"]
        for indicio in indicios_dm1:
            if indicio in texto_normalizado:
                contexto_seguro = False
                break
        
        if contexto_seguro:
            return cie10_encontrado, "CIE-10 (contexto seguro)"
    
    return None, "No encontrado"


def actualizar_base_datos(archivos_con_dm2, archivos_sin_dm2):
    """Actualiza la base de datos con los resultados del escaneo"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS DeteccionDM2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archivo TEXT NOT NULL,
                tiene_dm2 INTEGER NOT NULL,
                fecha_escaneo TEXT NOT NULL
            )
        ''')
        
        fecha_actual = datetime.now().isoformat()
        
        for archivo in archivos_con_dm2:
            cursor.execute(
                "INSERT INTO DeteccionDM2 (archivo, tiene_dm2, fecha_escaneo) VALUES (?, ?, ?)",
                (archivo, 1, fecha_actual)
            )
        
        for archivo in archivos_sin_dm2:
            cursor.execute(
                "INSERT INTO DeteccionDM2 (archivo, tiene_dm2, fecha_escaneo) VALUES (?, ?, ?)",
                (archivo, 0, fecha_actual)
            )
        
        conn.commit()
        conn.close()
        print(f"✅ Base de datos actualizada con {len(archivos_con_dm2) + len(archivos_sin_dm2)} registros")
        
    except Exception as e:
        print(f"❌ Error al actualizar la base de datos: {e}")

# =================== PROCESAMIENTO PRINCIPAL ===================
if not CARPETA_PDFS.exists():
    print(f"❌ La carpeta de PDFs no existe: {CARPETA_PDFS}")
    exit(1)

pdfs_con_dm2 = []
pdfs_sin_dm2 = []
pdfs_con_error = []
detalles_dm2 = {}

print(f"🔍 Escaneando PDFs en: {CARPETA_PDFS}")
print(f"📊 Patrones de búsqueda: {len(PATRONES_DM2_ALTA_PRIORIDAD)} alta prioridad, {len(PATRONES_DM2_MEDIA_PRIORIDAD)} media prioridad\n")

for archivo in os.listdir(CARPETA_PDFS):
    if archivo.lower().endswith(".pdf"):
        ruta_pdf = CARPETA_PDFS / archivo
        encontrado = False
        termino_encontrado = None
        contexto_encontrado = None
        categoria = None
        
        try:
            with pdfplumber.open(ruta_pdf) as pdf:
                for pagina_num, pagina in enumerate(pdf.pages):
                    try:
                        texto = pagina.extract_text() or ""
                        if texto:
                            termino, categoria = contiene_dm2_priorizado(texto)
                            if termino:
                                encontrado = True
                                termino_encontrado = termino
                                contexto_encontrado = encontrar_contexto_dm2(texto, termino)
                                break
                    except Exception:
                        continue
            
            if encontrado:
                pdfs_con_dm2.append(archivo)
                detalles_dm2[archivo] = {
                    'termino': termino_encontrado,
                    'contexto': contexto_encontrado,
                    'categoria': categoria
                }
                print(f"✅ {archivo}")
                print(f"   Término: {termino_encontrado}")
                print(f"   Categoría: {categoria}")
                print(f"   Contexto: {contexto_encontrado}")
                print()
            else:
                pdfs_sin_dm2.append(archivo)
                print(f"❌ {archivo} - Sin DM2")
                
        except Exception as e:
            print(f"⚠️ Error leyendo {archivo}: {e}")
            pdfs_con_error.append(archivo)

# =================== MOSTRAR RESULTADOS ===================
print("
" + "="*60)
print("📋 RESULTADOS DEL ESCANEO")
print("="*60)

if pdfs_con_dm2:
    print(f"✅ PDFs que SÍ mencionan DM2 ({len(pdfs_con_dm2)}):")
    for pdf in list(pdfs_con_dm2)[:3]:
        if pdf in detalles_dm2:
            print(f"   - {pdf}")
            print(f"     Término: {detalles_dm2[pdf]['termino']}")
            print(f"     Categoría: {detalles_dm2[pdf]['categoria']}")
            print(f"     Contexto: {detalles_dm2[pdf]['contexto']}")
            print()
    if len(pdfs_con_dm2) > 3:
        print(f"   ... y {len(pdfs_con_dm2) - 3} más")

if pdfs_sin_dm2:
    print(f"\n❌ PDFs que NO mencionan DM2 ({len(pdfs_sin_dm2)}):")
    for pdf in list(pdfs_sin_dm2)[:5]:
        print(f"   - {pdf}")
    if len(pdfs_sin_dm2) > 5:
        print(f"   ... y {len(pdfs_sin_dm2) - 5} más")

print("
" + "="*60)
print(f"📊 TOTAL: {len(pdfs_con_dm2) + len(pdfs_sin_dm2) + len(pdfs_con_error)} PDFs procesados")
print(f"   ✅ Con DM2: {len(pdfs_con_dm2)}")
print(f"   ❌ Sin DM2: {len(pdfs_sin_dm2)}")
print(f"   ⚠️ Con error: {len(pdfs_con_error)}")
print("="*60)

if args.mode == 'update-db':
    print("\n💾 Actualizando base de datos...")
    actualizar_base_datos(pdfs_con_dm2, pdfs_sin_dm2)