import os
import re
import sqlite3
import shutil
import asyncio
from datetime import datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

from database import crear_base


# ============================================================
# CONFIGURACIÓN
# ============================================================

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")

DB = "gastos.db"

# Confirmación temporal para borrar todos los gastos.
BORRAR_TODOS_PENDIENTE = set()

# Tarea del recordatorio de crédito.
RECORDATORIO_TASK = None

try:
    ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")
except Exception:
    ZONA_HORARIA = None


# ============================================================
# CATEGORÍAS
# ============================================================

CATEGORIAS = {
    "comida": "🍔 Comida",
    "supermercado": "🛒 Supermercado",
    "transporte": "🚗 Transporte",
    "hogar": "🏠 Hogar",
    "entretenimiento": "🎮 Entretenimiento",
    "salud": "💊 Salud",
    "educacion": "📚 Educación",
    "viajes": "✈️ Viajes",
    "tabaco": "🚬 Tabaco",
    "boliche": "🪩 Boliche",
    "weed": "🌿 Weed",
    "otros": "💳 Otros",
}


PALABRAS_CATEGORIAS = {

    "comida": [
        "comida",
        "almuerzo",
        "cena",
        "desayuno",
        "merienda",
        "restaurant",
        "restaurante",
        "parrilla",
        "pizza",
        "sushi",
        "hamburguesa",
        "hamburguesas",
        "empanada",
        "empanadas",
        "carne",
        "pollo",
        "vacío",
        "vacio",
        "entraña",
        "bife",
        "mcdonald",
        "mc donald",
        "burger",
        "helado",
        "rappi",
        "pedidos ya",
        "delivery",
        "cafe",
        "café",
        "bar",
    ],

    "supermercado": [
        "super",
        "supermercado",
        "carrefour",
        "coto",
        "disco",
        "jumbo",
        "dia",
        "día",
        "changomas",
        "chango mas",
        "verduleria",
        "verdulería",
        "almacen",
        "almacén",
    ],

    "transporte": [
        "uber",
        "cabify",
        "taxi",
        "colectivo",
        "subte",
        "tren",
        "nafta",
        "combustible",
        "gasolina",
        "estacionamiento",
        "peaje",
    ],

    "hogar": [
        "hogar",
        "casa",
        "alquiler",
        "expensas",
        "luz",
        "gas",
        "agua",
        "aysa",
        "internet",
        "mueble",
        "muebles",
        "ferreteria",
        "ferretería",
        "limpieza",
        "arreglo",
    ],

    "entretenimiento": [
        "cine",
        "netflix",
        "spotify",
        "hbo",
        "prime",
        "amazon",
        "playstation",
        "ps5",
        "xbox",
        "steam",
        "juego",
        "juegos",
        "teatro",
        "concierto",
        "entretenimiento",
    ],

    "salud": [
        "farmacia",
        "medico",
        "médico",
        "doctor",
        "hospital",
        "dentista",
        "odontologo",
        "odontólogo",
        "remedio",
        "medicamento",
        "salud",
    ],

    "educacion": [
        "facultad",
        "universidad",
        "curso",
        "libro",
        "libros",
        "educacion",
        "educación",
        "colegio",
    ],

    "viajes": [
        "hotel",
        "vuelo",
        "avion",
        "avión",
        "pasaje",
        "viaje",
        "airbnb",
        "booking",
        "turismo",
    ],

    "tabaco": [
        "cigarrillo",
        "cigarrillos",
        "cigarro",
        "tabaco",
        "pucho",
        "puchos",
        "vape",
    ],

    "boliche": [
        "boliche",
        "boliches",
        "disco",
        "fiesta",
        "entrada",
        "previa",
    ],

    "weed": [
        "weed",
        "marihuana",
        "porro",
        "porros",
    ],
}


MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


NOMBRES_MESES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


# ============================================================
# BASE DE DATOS
# ============================================================

def conectar():
    return sqlite3.connect(DB)


def crear_tablas_extra():

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        )
    """)

    # Migración segura para bases existentes.
    cursor.execute("PRAGMA table_info(gastos)")
    columnas = [fila[1] for fila in cursor.fetchall()]

    if "recordatorio_credito" not in columnas:

        cursor.execute("""
            ALTER TABLE gastos
            ADD COLUMN recordatorio_credito INTEGER NOT NULL DEFAULT 1
        """)

    conexion.commit()
    conexion.close()


# ============================================================
# CONFIGURACIÓN
# ============================================================

def guardar_config(clave, valor):

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO configuracion (clave, valor)
        VALUES (?, ?)
        ON CONFLICT(clave)
        DO UPDATE SET valor = excluded.valor
    """, (clave, str(valor)))

    conexion.commit()
    conexion.close()


def obtener_config(clave):

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT valor FROM configuracion WHERE clave = ?",
        (clave,)
    )

    resultado = cursor.fetchone()

    conexion.close()

    if resultado:
        return resultado[0]

    return None


# ============================================================
# UTILIDADES
# ============================================================

def ahora():

    if ZONA_HORARIA:
        return datetime.now(ZONA_HORARIA)

    return datetime.now()


def dinero(valor):

    valor = round(float(valor))

    signo = "-" if valor < 0 else ""

    valor = abs(valor)

    return f"{signo}${valor:,.0f}".replace(",", ".")


def mes_nombre(mes):

    if 1 <= mes <= 12:
        return NOMBRES_MESES[mes - 1]

    return ""


def primer_dia_mes(anio, mes):

    return datetime(
        anio,
        mes,
        1,
        tzinfo=ZONA_HORARIA
    )


def siguiente_mes(anio, mes):

    if mes == 12:
        return anio + 1, 1

    return anio, mes + 1


def rango_mes(anio, mes):

    inicio = primer_dia_mes(anio, mes)

    anio_fin, mes_fin = siguiente_mes(anio, mes)

    fin = primer_dia_mes(anio_fin, mes_fin)

    return inicio, fin


# ============================================================
# DETECCIÓN DE MONTO
# ============================================================

def detectar_monto(texto):

    texto = texto.replace("$", " ")

    patrones = [
        r"\b\d{1,3}(?:\.\d{3})+(?:,\d+)?\b",
        r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b",
        r"\b\d+(?:[.,]\d+)?\b",
    ]

    for patron in patrones:

        resultado = re.search(patron, texto)

        if not resultado:
            continue

        numero = resultado.group(0)

        # 1.300.000
        if numero.count(".") >= 1 and "," not in numero:
            partes = numero.split(".")

            if len(partes[-1]) == 3:
                numero = numero.replace(".", "")

        # 1,300,000
        elif numero.count(",") >= 1 and "." not in numero:
            partes = numero.split(",")

            if len(partes[-1]) == 3:
                numero = numero.replace(",", "")

            else:
                numero = numero.replace(",", ".")

        # 1.300.000,50
        elif "." in numero and "," in numero:

            if numero.rfind(",") > numero.rfind("."):
                numero = numero.replace(".", "")
                numero = numero.replace(",", ".")

            else:
                numero = numero.replace(",", "")

        try:
            return float(numero)

        except ValueError:
            continue

    return None


# ============================================================
# PERSONAS / GASTOS COMPARTIDOS
# ============================================================

def detectar_personas(texto):

    texto = texto.lower()

    patrones = [
        r"somos\s+(\d+)",
        r"entre\s+(\d+)",
        r"dividido\s+(\d+)",
        r"dividimos\s+(\d+)",
        r"\bx\s*(\d+)\b",
        r"para\s+(\d+)",
    ]

    for patron in patrones:

        resultado = re.search(patron, texto)

        if resultado:

            personas = int(resultado.group(1))

            if 2 <= personas <= 100:
                return personas

    return 1


# ============================================================
# MEDIO DE PAGO
# ============================================================

def detectar_medio_pago(texto):

    texto = texto.lower()

    if re.search(r"\bcr[eé]dito\b", texto):
        return "credito"

    if re.search(r"\bdebito\b|\bdébito\b", texto):
        return "debito"

    if re.search(r"\befectivo\b|\bcash\b", texto):
        return "efectivo"

    if re.search(r"\btransferencia\b|\btransferi\b", texto):
        return "transferencia"

    if "mercado pago" in texto or "mercadopago" in texto:
        return "mercado_pago"

    return "otro"


def nombre_medio_pago(medio):

    nombres = {
        "credito": "💳 Crédito",
        "debito": "💳 Débito",
        "efectivo": "💵 Efectivo",
        "transferencia": "🏦 Transferencia",
        "mercado_pago": "🟡 Mercado Pago",
        "otro": "💳 Otros",
    }

    return nombres.get(medio, medio)


# ============================================================
# CATEGORÍA
# ============================================================

def detectar_categoria(texto):

    texto = texto.lower()

    for categoria, palabras in PALABRAS_CATEGORIAS.items():

        for palabra in palabras:

            if palabra in texto:
                return CATEGORIAS[categoria]

    return CATEGORIAS["otros"]


def detectar_categoria_por_nombre(texto):

    texto = texto.lower()

    for clave, nombre in CATEGORIAS.items():

        if clave in texto:
            return nombre

        if nombre.lower() in texto:
            return nombre

    return None


# ============================================================
# MESES
# ============================================================

def detectar_mes(texto):

    texto = texto.lower()

    for nombre, numero in MESES.items():

        if re.search(rf"\b{nombre}\b", texto):
            return numero

    return None


def detectar_anio(texto):

    resultado = re.search(r"\b20\d{2}\b", texto)

    if resultado:
        return int(resultado.group(0))

    return ahora().year


# ============================================================
# GASTOS
# ============================================================

def insertar_gasto(
    monto,
    categoria,
    medio_pago,
    personas
):

    monto_personal = monto / personas

    fecha = ahora().strftime("%Y-%m-%d %H:%M:%S")

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO gastos
        (
            monto,
            categoria,
            medio_pago,
            personas,
            fecha,
            recordatorio_credito
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        monto_personal,
        categoria,
        medio_pago,
        personas,
        fecha,
        0 if medio_pago == "credito" else 1
    ))

    gasto_id = cursor.lastrowid

    conexion.commit()
    conexion.close()

    return gasto_id, monto_personal, fecha


def total_mes(anio, mes):

    inicio, fin = rango_mes(anio, mes)

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT COALESCE(SUM(monto), 0)
        FROM gastos
        WHERE fecha >= ?
        AND fecha < ?
    """, (
        inicio.strftime("%Y-%m-%d %H:%M:%S"),
        fin.strftime("%Y-%m-%d %H:%M:%S")
    ))

    resultado = cursor.fetchone()[0]

    conexion.close()

    return float(resultado or 0)


# ============================================================
# PRESUPUESTO
# ============================================================

def clave_presupuesto(anio, mes):

    return f"presupuesto_{anio:04d}_{mes:02d}"


def guardar_presupuesto(anio, mes, monto):

    guardar_config(
        clave_presupuesto(anio, mes),
        monto
    )

    # Guardamos el último presupuesto elegido.
    guardar_config(
        "ultimo_presupuesto_periodo",
        f"{anio:04d}-{mes:02d}"
    )


def obtener_presupuesto(anio, mes):

    valor = obtener_config(
        clave_presupuesto(anio, mes)
    )

    if valor is None:
        return None

    try:
        return float(valor)

    except ValueError:
        return None


def periodo_presupuesto_activo():

    fecha = ahora()

    # Primero usamos el presupuesto del mes actual.
    actual = obtener_presupuesto(
        fecha.year,
        fecha.month
    )

    if actual is not None:
        return fecha.year, fecha.month

    # Si no existe, usamos el último configurado,
    # por ejemplo octubre si todavía estamos en septiembre.
    ultimo = obtener_config(
        "ultimo_presupuesto_periodo"
    )

    if ultimo:

        try:
            anio, mes = ultimo.split("-")

            anio = int(anio)
            mes = int(mes)

            # Solo lo usamos si es un período futuro o actual.
            if (anio, mes) >= (fecha.year, fecha.month):
                return anio, mes

        except Exception:
            pass

    return fecha.year, fecha.month


# ============================================================
# CONFIGURAR PRESUPUESTO
# ============================================================

async def configurar_presupuesto(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    texto = update.message.text.lower()

    monto = detectar_monto(texto)

    if monto is None:
        return

    palabras_presupuesto = [
        "presupuesto",
        "arrancando",
        "arranco",
        "arrancar",
        "empiezo",
        "empiezo el mes",
        "tengo para",
    ]

    if not any(
        palabra in texto
        for palabra in palabras_presupuesto
    ):
        return

    mes = detectar_mes(texto)

    if mes is None:
        mes = ahora().month

    anio = detectar_anio(texto)

    guardar_presupuesto(
        anio,
        mes,
        monto
    )

    await responder_texto(update, 
        f"💰 {mes_nombre(mes).capitalize()}\n\n"
        f"Presupuesto establecido: {dinero(monto)}"
    )


# ============================================================
# CONSULTAR PRESUPUESTO
# ============================================================

async def consultar_presupuesto(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    anio, mes = periodo_presupuesto_activo()

    presupuesto = obtener_presupuesto(
        anio,
        mes
    )

    if presupuesto is None:

        await responder_texto(update, 
            f"💰 No tenés un presupuesto establecido para "
            f"{mes_nombre(mes).capitalize()}."
        )

        return

    gastado = total_mes(
        anio,
        mes
    )

    restante = presupuesto - gastado

    mensaje = (
        f"💰 {mes_nombre(mes).capitalize()}\n\n"
        f"Presupuesto: {dinero(presupuesto)}\n"
        f"Gastado: {dinero(gastado)}\n"
    )

    if restante >= 0:

        mensaje += (
            f"Te quedan: {dinero(restante)}"
        )

    else:

        mensaje += (
            f"Te pasaste: {dinero(abs(restante))}"
        )

    await responder_texto(update, 
        mensaje
    )


# ============================================================
# ALERTA CUANDO SE SUPERA EL PRESUPUESTO
# ============================================================

async def revisar_presupuesto(
    bot,
    anio,
    mes,
    total_anterior,
    total_nuevo
):

    presupuesto = obtener_presupuesto(
        anio,
        mes
    )

    if presupuesto is None:
        return

    # Solo avisamos cuando se cruza el presupuesto.
    if (
        total_anterior <= presupuesto
        and total_nuevo > presupuesto
    ):

        exceso = total_nuevo - presupuesto

        chat_id = obtener_config("chat_id")

        if not chat_id:
            return

        try:

            await bot.send_message(
                chat_id=int(chat_id),
                text=(
                    f"🚨 Te pasaste del presupuesto de "
                    f"{mes_nombre(mes)} por {dinero(exceso)}."
                )
            )

        except Exception as error:

            print(
                f"Error enviando alerta de presupuesto: {error}"
            )


# ============================================================
# REGISTRAR GASTO
# ============================================================

async def registrar_gasto(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    texto = update.message.text.strip()

    monto = detectar_monto(texto)

    if monto is None:
        return

    texto_lower = texto.lower()

    # No interpretar consultas como gastos.
    consultas = [
        "cuánto",
        "cuanto",
        "cómo",
        "como",
        "historial",
        "dashboard",
        "gráfico",
        "grafico",
        "compará",
        "compara",
        "borrar",
        "eliminar",
        "presupuesto",
        "cuánta plata me queda",
        "cuanta plata me queda",
    ]

    if any(
        palabra in texto_lower
        for palabra in consultas
    ):
        return

    categoria = detectar_categoria(
        texto
    )

    medio_pago = detectar_medio_pago(
        texto
    )

    personas = detectar_personas(
        texto
    )

    fecha_actual = ahora()

    total_anterior = total_mes(
        fecha_actual.year,
        fecha_actual.month
    )

    gasto_id, monto_personal, fecha = insertar_gasto(
        monto,
        categoria,
        medio_pago,
        personas
    )

    total_nuevo = total_anterior + monto_personal

    await revisar_presupuesto(
        context.bot,
        fecha_actual.year,
        fecha_actual.month,
        total_anterior,
        total_nuevo
    )

    if personas > 1:

        mensaje = (
            "✅ Gasto registrado\n\n"
            f"Total: {dinero(monto)}\n"
            f"Dividido entre: {personas}\n"
            f"Tu parte: {dinero(monto_personal)}\n\n"
            f"{categoria}\n"
            f"{nombre_medio_pago(medio_pago)}\n"
            f"ID: #{gasto_id}"
        )

    else:

        mensaje = (
            "✅ Gasto registrado\n\n"
            f"{dinero(monto_personal)}\n"
            f"{categoria}\n"
            f"{nombre_medio_pago(medio_pago)}\n"
            f"ID: #{gasto_id}"
        )

    await responder_texto(update, 
        mensaje
    )


# ============================================================
# HOY
# ============================================================

async def consulta_hoy(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    fecha = ahora()

    inicio = fecha.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    fin = inicio + timedelta(days=1)

    total = sumar_periodo(
        inicio,
        fin
    )

    await responder_texto(update, 
        f"💰 Hoy gastaste {dinero(total)}."
    )


# ============================================================
# AYER
# ============================================================

async def consulta_ayer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    fecha = ahora()

    hoy = fecha.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    inicio = hoy - timedelta(days=1)

    total = sumar_periodo(
        inicio,
        hoy
    )

    await responder_texto(update, 
        f"💰 Ayer gastaste {dinero(total)}."
    )


# ============================================================
# SUMAR PERÍODO
# ============================================================

def sumar_periodo(
    inicio,
    fin
):

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT COALESCE(SUM(monto), 0)
        FROM gastos
        WHERE fecha >= ?
        AND fecha < ?
    """, (
        inicio.strftime("%Y-%m-%d %H:%M:%S"),
        fin.strftime("%Y-%m-%d %H:%M:%S")
    ))

    total = cursor.fetchone()[0]

    conexion.close()

    return float(total or 0)


# ============================================================
# ESTA SEMANA
# ============================================================

async def consulta_semana(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    fecha = ahora()

    inicio = fecha - timedelta(
        days=fecha.weekday()
    )

    inicio = inicio.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    fin = inicio + timedelta(days=7)

    total = sumar_periodo(
        inicio,
        fin
    )

    await responder_texto(update, 
        f"📅 Esta semana gastaste {dinero(total)}."
    )


# ============================================================
# MES ACTUAL
# ============================================================

async def consulta_mes(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    fecha = ahora()

    inicio, fin = rango_mes(
        fecha.year,
        fecha.month
    )

    total = sumar_periodo(
        inicio,
        fin
    )

    await responder_texto(update, 
        f"💰 En {mes_nombre(fecha.month).capitalize()} "
        f"llevás gastados {dinero(total)}."
    )


# ============================================================
# MES ESPECÍFICO
# ============================================================

async def consulta_mes_especifico(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    texto = update.message.text.lower()

    mes = detectar_mes(texto)

    if mes is None:
        return

    anio = detectar_anio(texto)

    inicio, fin = rango_mes(
        anio,
        mes
    )

    total = sumar_periodo(
        inicio,
        fin
    )

    await responder_texto(update, 
        f"💰 En {mes_nombre(mes).capitalize()} "
        f"gastaste {dinero(total)}."
    )


# ============================================================
# CATEGORÍA DEL MES
# ============================================================

def total_categoria_mes(
    categoria,
    anio,
    mes
):

    inicio, fin = rango_mes(
        anio,
        mes
    )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT COALESCE(SUM(monto), 0)
        FROM gastos
        WHERE categoria = ?
        AND fecha >= ?
        AND fecha < ?
    """, (
        categoria,
        inicio.strftime("%Y-%m-%d %H:%M:%S"),
        fin.strftime("%Y-%m-%d %H:%M:%S")
    ))

    total = cursor.fetchone()[0]

    conexion.close()

    return float(total or 0)


async def consulta_categoria(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    texto = update.message.text.lower()

    categoria = detectar_categoria_por_nombre(
        texto
    )

    if not categoria:
        return

    fecha = ahora()

    total = total_categoria_mes(
        categoria,
        fecha.year,
        fecha.month
    )

    await responder_texto(update, 
        f"{categoria}\n\n"
        f"Este mes: {dinero(total)}"
    )


# ============================================================
# HISTORIAL
# ============================================================

async def historial(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            monto,
            categoria,
            medio_pago,
            personas,
            fecha
        FROM gastos
        ORDER BY id DESC
        LIMIT 30
    """)

    gastos = cursor.fetchall()

    conexion.close()

    if not gastos:

        await responder_texto(update, 
            "No hay gastos registrados."
        )

        return

    mensaje = "📋 Últimos gastos\n\n"

    for gasto in gastos:

        (
            gasto_id,
            monto,
            categoria,
            medio,
            personas,
            fecha
        ) = gasto

        mensaje += (
            f"#{gasto_id} — {dinero(monto)} — "
            f"{categoria} — "
            f"{nombre_medio_pago(medio)}\n"
        )

    await responder_texto(update, 
        mensaje
    )


# ============================================================
# ÚLTIMOS GASTOS DE UNA CATEGORÍA
# ============================================================

async def ultimos_gastos_categoria(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    texto = update.message.text.lower()

    categoria = detectar_categoria_por_nombre(
        texto
    )

    if not categoria:
        return

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            monto,
            medio_pago,
            fecha
        FROM gastos
        WHERE categoria = ?
        ORDER BY id DESC
        LIMIT 15
    """, (categoria,))

    gastos = cursor.fetchall()

    conexion.close()

    if not gastos:

        await responder_texto(update, 
            f"No encontré gastos de {categoria}."
        )

        return

    mensaje = (
        f"📋 Últimos gastos de {categoria}\n\n"
    )

    for gasto in gastos:

        gasto_id, monto, medio, fecha = gasto

        mensaje += (
            f"#{gasto_id} — {dinero(monto)} — "
            f"{nombre_medio_pago(medio)} — "
            f"{fecha}\n"
        )

    await responder_texto(update, 
        mensaje
    )


# ============================================================
# MAYOR GASTO
# ============================================================

async def mayor_gasto(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    fecha = ahora()

    inicio, fin = rango_mes(
        fecha.year,
        fecha.month
    )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT id, monto, categoria, medio_pago, fecha
        FROM gastos
        WHERE fecha >= ?
        AND fecha < ?
        ORDER BY monto DESC
        LIMIT 1
    """, (
        inicio.strftime("%Y-%m-%d %H:%M:%S"),
        fin.strftime("%Y-%m-%d %H:%M:%S")
    ))

    gasto = cursor.fetchone()

    conexion.close()

    if not gasto:

        await responder_texto(update, 
            "No tenés gastos este mes."
        )

        return

    gasto_id, monto, categoria, medio, fecha = gasto

    await responder_texto(update, 
        "💸 Mayor gasto del mes\n\n"
        f"{dinero(monto)}\n"
        f"{categoria}\n"
        f"{nombre_medio_pago(medio)}\n"
        f"ID: #{gasto_id}"
    )


# ============================================================
# GASTOS GRANDES
# ============================================================

async def gastos_grandes(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT id, monto, categoria, medio_pago, fecha
        FROM gastos
        ORDER BY monto DESC
        LIMIT 10
    """)

    gastos = cursor.fetchall()

    conexion.close()

    if not gastos:

        await responder_texto(update, 
            "No hay gastos registrados."
        )

        return

    mensaje = "💸 Gastos más grandes\n\n"

    for gasto in gastos:

        gasto_id, monto, categoria, medio, fecha = gasto

        mensaje += (
            f"#{gasto_id} — {dinero(monto)} — "
            f"{categoria}\n"
        )

    await responder_texto(update, 
        mensaje
    )


# ============================================================
# COMPARAR CATEGORÍAS
# ============================================================

async def comparar_categorias(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    fecha = ahora()

    valores = []

    for categoria in CATEGORIAS.values():

        total = total_categoria_mes(
            categoria,
            fecha.year,
            fecha.month
        )

        valores.append(
            (categoria, total)
        )

    valores.sort(
        key=lambda x: x[1],
        reverse=True
    )

    mensaje = (
        f"📊 Gastos por categoría — "
        f"{mes_nombre(fecha.month).capitalize()}\n\n"
    )

    for categoria, total in valores:

        if total > 0:

            mensaje += (
                f"{categoria}: {dinero(total)}\n"
            )

    if len(mensaje.splitlines()) == 2:

        mensaje += "Todavía no hay gastos."

    await responder_texto(update, 
        mensaje
    )


# ============================================================
# COMPARAR MESES
# ============================================================

async def comparar_meses(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    fecha = ahora()

    mes_actual = fecha.month
    anio_actual = fecha.year

    if mes_actual == 1:

        mes_anterior = 12
        anio_anterior = anio_actual - 1

    else:

        mes_anterior = mes_actual - 1
        anio_anterior = anio_actual

    total_actual = total_mes(
        anio_actual,
        mes_actual
    )

    total_anterior = total_mes(
        anio_anterior,
        mes_anterior
    )

    diferencia = total_actual - total_anterior

    mensaje = (
        "📊 Comparación\n\n"
        f"{mes_nombre(mes_anterior).capitalize()}: "
        f"{dinero(total_anterior)}\n"
        f"{mes_nombre(mes_actual).capitalize()}: "
        f"{dinero(total_actual)}\n\n"
    )

    if diferencia > 0:

        mensaje += (
            f"Este mes llevás {dinero(diferencia)} "
            f"más que el anterior."
        )

    elif diferencia < 0:

        mensaje += (
            f"Este mes llevás {dinero(abs(diferencia))} "
            f"menos que el anterior."
        )

    else:

        mensaje += "Gastaste lo mismo."

    await responder_texto(update, 
        mensaje
    )


# ============================================================
# MEDIOS DE PAGO
# ============================================================

async def consulta_medio_pago(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    texto = update.message.text.lower()

    medios = {
        "crédito": "credito",
        "credito": "credito",
        "débito": "debito",
        "debito": "debito",
        "efectivo": "efectivo",
        "transferencia": "transferencia",
        "mercado pago": "mercado_pago",
    }

    medio = None

    for palabra, valor in medios.items():

        if palabra in texto:
            medio = valor
            break

    if medio is None:
        return

    fecha = ahora()

    inicio, fin = rango_mes(
        fecha.year,
        fecha.month
    )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT COALESCE(SUM(monto), 0)
        FROM gastos
        WHERE medio_pago = ?
        AND fecha >= ?
        AND fecha < ?
    """, (
        medio,
        inicio.strftime("%Y-%m-%d %H:%M:%S"),
        fin.strftime("%Y-%m-%d %H:%M:%S")
    ))

    total = cursor.fetchone()[0]

    conexion.close()

    await responder_texto(update, 
        f"{nombre_medio_pago(medio)}\n\n"
        f"Este mes: {dinero(total)}"
    )


# ============================================================
# BORRAR ÚLTIMO
# ============================================================

async def borrar_ultimo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT id, monto, categoria
        FROM gastos
        ORDER BY id DESC
        LIMIT 1
    """)

    gasto = cursor.fetchone()

    if not gasto:

        conexion.close()

        await responder_texto(update, 
            "No hay gastos para borrar."
        )

        return

    gasto_id, monto, categoria = gasto

    cursor.execute(
        "DELETE FROM gastos WHERE id = ?",
        (gasto_id,)
    )

    conexion.commit()
    conexion.close()

    await responder_texto(update, 
        f"🗑️ Borrado #{gasto_id}\n"
        f"{dinero(monto)} — {categoria}"
    )


# ============================================================
# BORRAR POR ID
# ============================================================

async def borrar_por_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    texto = update.message.text

    numeros = re.findall(
        r"\d+",
        texto
    )

    if not numeros:

        await responder_texto(update, 
            "Decime el número del gasto.\n"
            "Ejemplo: borrar gasto 15"
        )

        return

    gasto_id = int(
        numeros[-1]
    )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT monto, categoria
        FROM gastos
        WHERE id = ?
    """, (gasto_id,))

    gasto = cursor.fetchone()

    if not gasto:

        conexion.close()

        await responder_texto(update, 
            f"No existe el gasto #{gasto_id}."
        )

        return

    monto, categoria = gasto

    cursor.execute(
        "DELETE FROM gastos WHERE id = ?",
        (gasto_id,)
    )

    conexion.commit()
    conexion.close()

    await responder_texto(update, 
        f"🗑️ Borrado #{gasto_id}\n"
        f"{dinero(monto)} — {categoria}"
    )


# ============================================================
# EDITAR GASTO
# ============================================================

async def editar_gasto(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    texto = update.message.text

    ids = re.findall(
        r"#?(\d+)",
        texto
    )

    if not ids:

        await responder_texto(update, 
            "Ejemplo:\n"
            "Corregí el gasto #15, eran 25000"
        )

        return

    gasto_id = int(
        ids[0]
    )

    montos = []

    patron_montos = [
        r"\$?\d{1,3}(?:\.\d{3})+",
        r"\$?\d+",
    ]

    for patron in patron_montos:

        for coincidencia in re.findall(
            patron,
            texto
        ):

            monto = detectar_monto(
                coincidencia
            )

            if monto is not None:
                montos.append(monto)

    if len(montos) < 2:

        await responder_texto(update, 
            "Necesito el nuevo monto.\n"
            "Ejemplo: Corregí el gasto #15, eran 25000"
        )

        return

    nuevo_monto = montos[-1]

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT id, monto, categoria, personas
        FROM gastos
        WHERE id = ?
    """, (gasto_id,))

    gasto = cursor.fetchone()

    if not gasto:

        conexion.close()

        await responder_texto(update, 
            f"No encontré el gasto #{gasto_id}."
        )

        return

    cursor.execute("""
        UPDATE gastos
        SET monto = ?
        WHERE id = ?
    """, (
        nuevo_monto,
        gasto_id
    ))

    conexion.commit()
    conexion.close()

    await responder_texto(update, 
        f"✏️ Gasto #{gasto_id} corregido.\n"
        f"Nuevo monto: {dinero(nuevo_monto)}"
    )


# ============================================================
# RESPUESTA DE TEXTO COMPATIBLE CON BOTONES
# ============================================================

async def responder_texto(update: Update, texto: str, **kwargs):

    if update.message:
        return await update.message.reply_text(
            texto,
            **kwargs
        )

    if update.callback_query and update.callback_query.message:
        return await update.callback_query.message.reply_text(
            texto,
            **kwargs
        )


# ============================================================
# GRÁFICO POR CATEGORÍA
# ============================================================

async def grafico_categorias(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    fecha = ahora()

    valores = []

    for categoria in CATEGORIAS.values():

        total = total_categoria_mes(
            categoria,
            fecha.year,
            fecha.month
        )

        if total > 0:
            valores.append(
                (categoria, total)
            )

    if not valores:

        await responder_texto(update, 
            "Todavía no hay gastos para graficar."
        )

        return

    valores.sort(
        key=lambda x: x[1]
    )

    nombres = [
        x[0] for x in valores
    ]

    montos = [
        x[1] for x in valores
    ]

    total_general = sum(montos)

    fig, ax = plt.subplots(
        figsize=(10, 7)
    )

    barras = ax.barh(
        nombres,
        montos
    )

    ax.set_title(
        f"Gastos por categoría — "
        f"{mes_nombre(fecha.month).capitalize()}"
    )

    ax.set_xlabel(
        "Pesos"
    )

    for barra, monto in zip(
        barras,
        montos
    ):

        porcentaje = (
            monto / total_general * 100
        )

        ax.text(
            monto,
            barra.get_y() + barra.get_height() / 2,
            f" {dinero(monto)} ({porcentaje:.0f}%)",
            va="center"
        )

    plt.tight_layout()

    buffer = BytesIO()

    plt.savefig(
        buffer,
        format="png",
        dpi=180,
        bbox_inches="tight"
    )

    plt.close()

    buffer.seek(0)

    await update.message.reply_photo(
        photo=buffer,
        caption="📊 Gastos por categoría"
    )


# ============================================================
# GRÁFICO DIARIO
# ============================================================

async def grafico_diario(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    fecha = ahora()

    inicio, fin = rango_mes(
        fecha.year,
        fecha.month
    )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            substr(fecha, 1, 10) AS dia,
            SUM(monto)
        FROM gastos
        WHERE fecha >= ?
        AND fecha < ?
        GROUP BY substr(fecha, 1, 10)
        ORDER BY dia
    """, (
        inicio.strftime("%Y-%m-%d %H:%M:%S"),
        fin.strftime("%Y-%m-%d %H:%M:%S")
    ))

    datos = cursor.fetchall()

    conexion.close()

    if not datos:

        await responder_texto(update, 
            "Todavía no hay gastos para graficar."
        )

        return

    dias = [
        x[0][-2:]
        for x in datos
    ]

    montos = [
        float(x[1])
        for x in datos
    ]

    promedio = sum(montos) / len(montos)

    fig, ax = plt.subplots(
        figsize=(11, 6)
    )

    ax.plot(
        dias,
        montos,
        marker="o",
        linewidth=2
    )

    ax.axhline(
        promedio,
        linestyle="--",
        label=f"Promedio: {dinero(promedio)}"
    )

    for dia, monto in zip(
        dias,
        montos
    ):

        ax.annotate(
            dinero(monto),
            (dia, monto),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=8
        )

    ax.set_title(
        f"Gasto diario — "
        f"{mes_nombre(fecha.month).capitalize()}"
    )

    ax.set_xlabel("Día")
    ax.set_ylabel("Pesos")

    ax.legend()

    plt.tight_layout()

    buffer = BytesIO()

    plt.savefig(
        buffer,
        format="png",
        dpi=180,
        bbox_inches="tight"
    )

    plt.close()

    buffer.seek(0)

    await update.message.reply_photo(
        photo=buffer,
        caption="📈 Gasto diario"
    )


# ============================================================
# GRÁFICO MENSUAL
# ============================================================

async def grafico_mensual(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    fecha = ahora()

    datos = []

    for i in range(6):

        mes = fecha.month - i
        anio = fecha.year

        while mes <= 0:

            mes += 12
            anio -= 1

        total = total_mes(
            anio,
            mes
        )

        datos.append(
            (
                f"{mes_nombre(mes)[:3].capitalize()}",
                total
            )
        )

    datos.reverse()

    nombres = [
        x[0] for x in datos
    ]

    montos = [
        x[1] for x in datos
    ]

    fig, ax = plt.subplots(
        figsize=(10, 6)
    )

    barras = ax.bar(
        nombres,
        montos
    )

    ax.set_title(
        "Gastos de los últimos 6 meses"
    )

    ax.set_ylabel(
        "Pesos"
    )

    for barra, monto in zip(
        barras,
        montos
    ):

        ax.text(
            barra.get_x() + barra.get_width() / 2,
            barra.get_height(),
            dinero(monto),
            ha="center",
            va="bottom",
            fontsize=9
        )

    plt.tight_layout()

    buffer = BytesIO()

    plt.savefig(
        buffer,
        format="png",
        dpi=180,
        bbox_inches="tight"
    )

    plt.close()

    buffer.seek(0)

    await update.message.reply_photo(
        photo=buffer,
        caption="📊 Evolución mensual"
    )


# ============================================================
# DASHBOARD
# ============================================================

async def dashboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    fecha = ahora()

    total = total_mes(
        fecha.year,
        fecha.month
    )

    presupuesto = obtener_presupuesto(
        fecha.year,
        fecha.month
    )

    mensaje = (
        f"📊 Dashboard — "
        f"{mes_nombre(fecha.month).capitalize()}\n\n"
        f"💰 Gastado: {dinero(total)}\n"
    )

    if presupuesto is not None:

        restante = presupuesto - total

        mensaje += (
            f"💼 Presupuesto: {dinero(presupuesto)}\n"
            f"💵 Te quedan: {dinero(restante)}\n"
        )

    # Categoría principal
    valores = []

    for categoria in CATEGORIAS.values():

        valor = total_categoria_mes(
            categoria,
            fecha.year,
            fecha.month
        )

        if valor > 0:
            valores.append(
                (categoria, valor)
            )

    valores.sort(
        key=lambda x: x[1],
        reverse=True
    )

    if valores:

        mensaje += "\n🏆 Categorías:\n"

        for categoria, valor in valores[:5]:

            mensaje += (
                f"{categoria}: {dinero(valor)}\n"
            )

    await responder_texto(update, 
        mensaje
    )


# ============================================================
# BACKUP
# ============================================================

async def backup(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not os.path.exists(DB):

        await responder_texto(update, 
            "No existe la base de datos."
        )

        return

    nombre = (
        f"gastos_backup_"
        f"{ahora().strftime('%Y%m%d_%H%M%S')}.db"
    )

    shutil.copy2(
        DB,
        nombre
    )

    try:

        with open(
            nombre,
            "rb"
        ) as archivo:

            await update.message.reply_document(
                document=archivo,
                filename=nombre
            )

    finally:

        if os.path.exists(nombre):
            os.remove(nombre)


# ============================================================
# CRÉDITO
# ============================================================

async def gastos_credito_pendientes():

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            monto,
            fecha
        FROM gastos
        WHERE medio_pago = 'credito'
        AND recordatorio_credito = 0
        ORDER BY fecha ASC
    """)

    gastos = cursor.fetchall()

    conexion.close()

    return gastos


def marcar_credito_recordado(ids):

    if not ids:
        return

    conexion = conectar()
    cursor = conexion.cursor()

    placeholders = ",".join(
        ["?"] * len(ids)
    )

    cursor.execute(
        f"""
        UPDATE gastos
        SET recordatorio_credito = 1
        WHERE id IN ({placeholders})
        """,
        ids
    )

    conexion.commit()
    conexion.close()


async def enviar_recordatorio_credito(
    application
):

    chat_id = obtener_config(
        "chat_id"
    )

    if not chat_id:
        return

    try:
        chat_id = int(chat_id)

    except ValueError:
        return

    gastos = await gastos_credito_pendientes()

    if not gastos:
        return

    fecha_actual = ahora()

    # Corte de las 22:00.
    corte_hoy = fecha_actual.replace(
        hour=22,
        minute=0,
        second=0,
        microsecond=0
    )

    ids_validos = []

    agrupados = {}

    for gasto_id, monto, fecha_texto in gastos:

        try:

            fecha_gasto = datetime.strptime(
                fecha_texto,
                "%Y-%m-%d %H:%M:%S"
            )

            if ZONA_HORARIA:
                fecha_gasto = fecha_gasto.replace(
                    tzinfo=ZONA_HORARIA
                )

        except Exception:
            continue

        # Si es un gasto de hoy posterior a las 22,
        # NO entra en el recordatorio de hoy.
        if (
            fecha_gasto.date() == fecha_actual.date()
            and fecha_gasto > corte_hoy
        ):
            continue

        ids_validos.append(
            gasto_id
        )

        fecha_clave = fecha_gasto.date()

        agrupados[fecha_clave] = (
            agrupados.get(fecha_clave, 0)
            + float(monto)
        )

    if not ids_validos:
        return

    total = sum(
        agrupados.values()
    )

    # Si todo corresponde a hoy.
    if (
        len(agrupados) == 1
        and fecha_actual.date() in agrupados
    ):

        mensaje = (
            "💳 Acordate:\n\n"
            f"Hoy gastaste {dinero(total)} "
            "con crédito.\n"
            "Separá esa plata de tu cuenta."
        )

    else:

        mensaje = (
            "💳 Acordate de separar de tu cuenta:\n\n"
            f"Total: {dinero(total)}\n\n"
        )

        for fecha_gasto, monto in sorted(
            agrupados.items()
        ):

            if fecha_gasto == fecha_actual.date():

                etiqueta = "Hoy"

            elif fecha_gasto == (
                fecha_actual.date()
                - timedelta(days=1)
            ):

                etiqueta = "Ayer"

            else:

                etiqueta = fecha_gasto.strftime(
                    "%d/%m"
                )

            mensaje += (
                f"• {etiqueta}: "
                f"{dinero(monto)}\n"
            )

    try:

        await application.bot.send_message(
            chat_id=chat_id,
            text=mensaje
        )

        marcar_credito_recordado(
            ids_validos
        )

    except Exception as error:

        print(
            f"Error enviando recordatorio de crédito: "
            f"{error}"
        )


async def loop_recordatorio_credito(
    application
):

    ultima_fecha = None

    while True:

        try:

            fecha = ahora()

            fecha_hoy = fecha.date()

            if (
                fecha.hour >= 22
                and ultima_fecha != fecha_hoy
            ):

                await enviar_recordatorio_credito(
                    application
                )

                ultima_fecha = fecha_hoy

        except Exception as error:

            print(
                f"Error en loop de crédito: {error}"
            )

        await asyncio.sleep(30)


async def iniciar_recordatorio(
    application
):

    global RECORDATORIO_TASK

    # asyncio.create_task() evita el warning de PTB porque
    # post_init ocurre antes de que Application esté marcada
    # como running.
    RECORDATORIO_TASK = asyncio.create_task(
        loop_recordatorio_credito(
            application
        )
    )


async def detener_recordatorio(
    application
):

    global RECORDATORIO_TASK

    if RECORDATORIO_TASK is not None:

        RECORDATORIO_TASK.cancel()

        try:
            await RECORDATORIO_TASK

        except asyncio.CancelledError:
            pass

        RECORDATORIO_TASK = None


# ============================================================
# GUARDAR CHAT ID
# ============================================================

async def registrar_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_chat:
        return

    if update.effective_chat.type != "private":
        return

    guardar_config(
        "chat_id",
        update.effective_chat.id
    )



# ============================================================
# MENÚ DE BOTONES
# ============================================================

def teclado_principal():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Agregar gasto", callback_data="menu_agregar"),
            InlineKeyboardButton("📊 Resumen", callback_data="menu_resumen"),
        ],
        [
            InlineKeyboardButton("📅 Hoy", callback_data="menu_hoy"),
            InlineKeyboardButton("📆 Este mes", callback_data="menu_mes"),
        ],
        [
            InlineKeyboardButton("💰 Presupuesto", callback_data="menu_presupuesto"),
            InlineKeyboardButton("📋 Historial", callback_data="menu_historial"),
        ],
        [
            InlineKeyboardButton("📈 Gráficos", callback_data="menu_graficos"),
            InlineKeyboardButton("💳 Crédito", callback_data="menu_credito"),
        ],
        [
            InlineKeyboardButton("✏️ Corregir / borrar", callback_data="menu_editar"),
            InlineKeyboardButton("❓ Ayuda", callback_data="menu_ayuda"),
        ],
    ])


def teclado_borrar():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑️ Borrar último", callback_data="borrar_ultimo"),
            InlineKeyboardButton("🗑️ Borrar todos", callback_data="confirmar_borrar_todos"),
        ],
        [
            InlineKeyboardButton("↩️ Volver", callback_data="menu_principal"),
        ],
    ])


def teclado_confirmar_borrado():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ SÍ, borrar todos", callback_data="borrar_todos_confirmado"),
            InlineKeyboardButton("❌ Cancelar", callback_data="menu_principal"),
        ]
    ])


async def menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "🏠 Menú principal\n\n"
            "También podés escribir cualquier pedido normalmente.",
            reply_markup=teclado_principal()
        )
        return

    await responder_texto(update, 
        "🏠 Menú principal\n\n"
        "También podés escribir cualquier pedido normalmente.",
        reply_markup=teclado_principal()
    )


async def manejar_botones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    if data == "menu_principal":
        await query.edit_message_text(
            "🏠 Menú principal\n\n"
            "También podés escribir cualquier pedido normalmente.",
            reply_markup=teclado_principal()
        )
        return

    if data == "menu_agregar":
        await query.edit_message_text(
            "➕ Agregar gasto\n\n"
            "Escribime el gasto como quieras.\n\n"
            "Ejemplos:\n"
            "• 15000 comida débito\n"
            "• 40000 cena somos 4 crédito\n"
            "• gasté 12000 en supermercado",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Volver", callback_data="menu_principal")]
            ])
        )
        return

    if data == "menu_resumen":
        await query.edit_message_text(
            "📊 Para ver un resumen escribime:\n\n"
            "• resumen\n"
            "• dashboard\n"
            "• cuánto gasté hoy\n"
            "• cuánto llevo gastado este mes",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Dashboard", callback_data="accion_dashboard")],
                [InlineKeyboardButton("📅 Hoy", callback_data="accion_hoy")],
                [InlineKeyboardButton("↩️ Volver", callback_data="menu_principal")]
            ])
        )
        return

    if data == "accion_dashboard":
        await query.edit_message_text("⏳ Cargando resumen...")
        await dashboard(update, context)
        return

    if data == "accion_hoy":
        await query.edit_message_text("⏳ Cargando...")
        await consulta_hoy(update, context)
        return

    if data == "menu_hoy":
        await query.edit_message_text("⏳ Cargando...")
        await consulta_hoy(update, context)
        return

    if data == "menu_mes":
        await query.edit_message_text("⏳ Cargando...")
        await consulta_mes(update, context)
        return

    if data == "menu_presupuesto":
        await query.edit_message_text(
            "💰 Presupuesto\n\n"
            "Podés decirme, por ejemplo:\n"
            "• Estoy arrancando octubre con 1300000\n"
            "• Cuánta plata me queda\n"
            "• Cómo vengo con el presupuesto",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💵 ¿Cuánto me queda?", callback_data="accion_presupuesto")],
                [InlineKeyboardButton("↩️ Volver", callback_data="menu_principal")]
            ])
        )
        return

    if data == "accion_presupuesto":
        await query.edit_message_text("⏳ Cargando...")
        await consultar_presupuesto(update, context)
        return

    if data == "menu_historial":
        await query.edit_message_text("⏳ Cargando historial...")
        await historial(update, context)
        return

    if data == "menu_graficos":
        await query.edit_message_text(
            "📈 Gráficos\n\nElegí qué querés ver:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Por categoría", callback_data="grafico_categorias")],
                [InlineKeyboardButton("📅 Diario", callback_data="grafico_diario")],
                [InlineKeyboardButton("📆 Mensual", callback_data="grafico_mensual")],
                [InlineKeyboardButton("↩️ Volver", callback_data="menu_principal")]
            ])
        )
        return

    if data in {"grafico_categorias", "grafico_diario", "grafico_mensual"}:
        await query.edit_message_text("⏳ Generando gráfico...")
        if data == "grafico_categorias":
            await grafico_categorias(update, context)
        elif data == "grafico_diario":
            await grafico_diario(update, context)
        else:
            await grafico_mensual(update, context)
        return

    if data == "menu_credito":
        await query.edit_message_text(
            "💳 Crédito\n\n"
            "Los gastos con crédito descuentan del presupuesto igual que cualquier otro gasto.\n\n"
            "A las 22:00 te recuerdo separar de tu cuenta la plata que gastaste con crédito.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Volver", callback_data="menu_principal")]
            ])
        )
        return

    if data == "menu_editar":
        await query.edit_message_text(
            "✏️ Corregir / borrar\n\n"
            "Podés escribir:\n"
            "• borrar último\n"
            "• borrar gasto 15\n"
            "• corregir gasto 15\n\n"
            "O usar estas opciones:",
            reply_markup=teclado_borrar()
        )
        return

    if data == "borrar_ultimo":
        await query.edit_message_text("⏳ Borrando...")
        await borrar_ultimo(update, context)
        return

    if data == "confirmar_borrar_todos":
        chat_id = update.effective_chat.id
        BORRAR_TODOS_PENDIENTE.add(chat_id)
        await query.edit_message_text(
            "⚠️ ¿Seguro que querés borrar TODOS los gastos?\n\n"
            "Esta acción elimina todos los registros de gastos y no se puede deshacer.",
            reply_markup=teclado_confirmar_borrado()
        )
        return

    if data == "borrar_todos_confirmado":
        chat_id = update.effective_chat.id
        if chat_id not in BORRAR_TODOS_PENDIENTE:
            await query.edit_message_text(
                "La confirmación expiró.",
                reply_markup=teclado_principal()
            )
            return

        BORRAR_TODOS_PENDIENTE.discard(chat_id)

        conexion = conectar()
        cursor = conexion.cursor()
        cursor.execute("SELECT COUNT(*) FROM gastos")
        cantidad = cursor.fetchone()[0]
        cursor.execute("DELETE FROM gastos")
        conexion.commit()
        conexion.close()

        await query.edit_message_text(
            f"🗑️ Listo. Borré {cantidad} gastos.\n\n"
            "El presupuesto no se modificó.",
            reply_markup=teclado_principal()
        )
        return

    if data == "menu_ayuda":
        await query.edit_message_text(
            "❓ Ayuda\n\n"
            "Podés escribir naturalmente:\n"
            "• 15000 cena débito\n"
            "• 40000 cena somos 4 crédito\n"
            "• cuánto gasté hoy\n"
            "• cuánto llevo gastado este mes\n"
            "• cuánto gasté en comida este mes\n"
            "• historial\n"
            "• dashboard\n"
            "• gráficos\n"
            "• borrar último\n"
            "• borrar gasto 15\n"
            "• estoy arrancando octubre con 1300000\n"
            "• cuánta plata me queda",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menú", callback_data="menu_principal")]
            ])
        )
        return


async def borrar_todos_por_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto = (update.message.text or "").strip().lower()

    if chat_id not in BORRAR_TODOS_PENDIENTE:
        BORRAR_TODOS_PENDIENTE.add(chat_id)
        await responder_texto(update, 
            "⚠️ Esto va a borrar TODOS los gastos.\n\n"
            "Si estás seguro, escribí **SI BORRAR TODO**.",
            parse_mode="Markdown"
        )
        return

    if texto in {"si borrar todo", "sí borrar todo", "confirmar", "si", "sí"}:
        BORRAR_TODOS_PENDIENTE.discard(chat_id)

        conexion = conectar()
        cursor = conexion.cursor()
        cursor.execute("SELECT COUNT(*) FROM gastos")
        cantidad = cursor.fetchone()[0]
        cursor.execute("DELETE FROM gastos")
        conexion.commit()
        conexion.close()

        await responder_texto(update, 
            f"🗑️ Listo. Borré {cantidad} gastos.\n\n"
            "El presupuesto no se modificó."
        )
    else:
        BORRAR_TODOS_PENDIENTE.discard(chat_id)
        await responder_texto(update, "❌ Cancelado. No borré nada.")


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_chat:

        guardar_config(
            "chat_id",
            update.effective_chat.id
        )

    await responder_texto(update, 
        "👋 Soy tu bot de gastos.\n\n"
        "Podés escribirme naturalmente:\n\n"
        "💸 Gastos\n"
        "• Gasté 15000 en comida con débito\n"
        "• 40000 cena somos 4 crédito\n\n"
        "📊 Consultas\n"
        "• Cuánto gasté hoy\n"
        "• Cuánto llevo gastado este mes\n"
        "• Cuánto gasté en comida este mes\n\n"
        "💰 Presupuesto\n"
        "• Estoy arrancando octubre con 1.300.000\n"
        "• ¿Cómo vengo con el presupuesto?\n"
        "• ¿Cuánta plata me queda?\n\n"
        "📋 También podés pedir historial, gráficos, "
        "dashboard, borrar o corregir gastos.",
        reply_markup=teclado_principal()
    )


# ============================================================
# HANDLERS
# ============================================================

def configurar_handlers(
    app
):

    # Registrar siempre el chat privado.
    app.add_handler(
        TypeHandler(
            Update,
            registrar_chat
        ),
        group=-1
    )

    # Comandos.
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "backup",
            backup
        )
    )

    # Botones del menú.
    app.add_handler(
        CallbackQueryHandler(
            manejar_botones
        )
    )

    # --------------------------------------------------------
    # PRESUPUESTO
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(presupuesto|arrancando|arranco|empiezo).*"
            ),
            configurar_presupuesto
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(cómo vengo con el presupuesto|como vengo con el presupuesto|cuánta plata me queda|cuanta plata me queda|cuánto me queda de presupuesto|cuanto me queda de presupuesto).*"
            ),
            consultar_presupuesto
        )
    )

    # --------------------------------------------------------
    # CONSULTAS
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i)^(¿?cuánto|¿?cuanto) gast[eé] hoy\??$"
            ),
            consulta_hoy
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i)^(¿?cuánto|¿?cuanto) gast[eé] ayer\??$"
            ),
            consulta_ayer
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(cuánto|cuanto) gast[eé] esta semana.*"
            ),
            consulta_semana
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(cuánto|cuanto) llev[oó] gastado este mes.*"
            ),
            consulta_mes
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(cuánto|cuanto) gast[eé] en (enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre).*"
            ),
            consulta_mes_especifico
        )
    )

    # --------------------------------------------------------
    # DASHBOARD / GRÁFICOS
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i)^\s*dashboard\s*$"
            ),
            dashboard
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(gr[aá]fico|grafico).*(categor[ií]a|categorias).*"
            ),
            grafico_categorias
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(gr[aá]fico|grafico).*(diario|d[ií]a).*"
            ),
            grafico_diario
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(gr[aá]fico|grafico).*(mensual|meses).*"
            ),
            grafico_mensual
        )
    )

    # --------------------------------------------------------
    # COMPARACIONES
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(compar[aá]|comparar).*(categor[ií]a|categorias).*"
            ),
            comparar_categorias
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(compar[aá]|comparar).*(mes|meses|anterior).*"
            ),
            comparar_meses
        )
    )

    # --------------------------------------------------------
    # HISTORIAL
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(historial|hist[oó]rico|últimos gastos|ultimos gastos).*"
            ),
            historial
        )
    )

    # --------------------------------------------------------
    # MAYORES GASTOS
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(mayor gasto|gasto m[aá]s grande).*"
            ),
            mayor_gasto
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(gastos grandes|gastos m[aá]s altos).*"
            ),
            gastos_grandes
        )
    )

    # --------------------------------------------------------
    # MEDIOS DE PAGO
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(cuánto|cuanto).*(cr[eé]dito|d[eé]bito|efectivo|transferencia|mercado pago).*"
            ),
            consulta_medio_pago
        )
    )

    # --------------------------------------------------------
    # CATEGORÍAS
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(cuánto|cuanto).*(comida|supermercado|transporte|hogar|entretenimiento|salud|educaci[oó]n|viajes|tabaco|boliche|weed).*"
            ),
            consulta_categoria
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(mostrame|mostrar|ver|últimos|ultimos).*(comida|supermercado|transporte|hogar|entretenimiento|salud|educaci[oó]n|viajes|tabaco|boliche|weed).*"
            ),
            ultimos_gastos_categoria
        )
    )

    # --------------------------------------------------------
    # EDITAR / BORRAR
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(correg[ií]|editar|cambiar).*(gasto).*"
            ),
            editar_gasto
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i)^\\s*(borrar|eliminar)\\s+(todos|todo)(\\s+los\\s+gastos)?\\s*$"
            ),
            borrar_todos_por_texto
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(borrar|eliminar).*(último|ultimo).*"
            ),
            borrar_ultimo
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i).*(borrar|eliminar).*\d+.*"
            ),
            borrar_por_id
        )
    )

    # --------------------------------------------------------
    # BACKUP POR TEXTO
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                r"(?i)^backup$"
            ),
            backup
        )
    )

    # --------------------------------------------------------
    # GASTO GENERAL
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            registrar_gasto
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not TOKEN:

        print(
            "ERROR: no se encontró TELEGRAM_TOKEN en .env"
        )

        return

    crear_base()

    crear_tablas_extra()

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(iniciar_recordatorio)
        .post_shutdown(detener_recordatorio)
        .build()
    )

    configurar_handlers(
        app
    )

    print(
        "Bot iniciado..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()