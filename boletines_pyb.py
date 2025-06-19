import streamlit as st
import pandas as pd
import pytz
from datetime import datetime, timedelta, date
import requests
import feedparser
import fitz
import unicodedata
import re
from dateutil import parser as date_parser

# ---------------- CONFIGURACIÓN ---------------- #

keywords = [
    "Ley", "Ley Orgánica", "Decreto Ley", "Decreto Legislativo",
    "Texto Refundido", "Reglamento", "Ordenación", "Urbanismo", "Decreto-Ley",
    "Instrumento de planeamiento", "Planeamiento", "Plan Insular", "Plan General",
    "Plan Especial", "Plan Parcial", "Plan Modernización", "Modificación puntual del P.G.O.",
    "Proyecto de urbanización", "Ordenanza Provisional", "Ordenanza municipal de urbanización", "Urbanización",
    "Edificación", "Catálogo de protección", "Evaluación Ambiental",
]
keywords_normalizadas = [''.join(
    c for c in unicodedata.normalize('NFKD', kw)
    if not unicodedata.combining(c)
).lower() for kw in keywords]

tz_canarias = pytz.timezone("Atlantic/Canary")
hoy = datetime.now(tz_canarias).date()
anio_actual = hoy.year

# ---------------- FUNCIONES ---------------- #

def normalizar(texto):
    return ''.join(
        c for c in unicodedata.normalize('NFKD', texto)
        if not unicodedata.combining(c)
    ).lower()

def calcular_numero_boc(fecha_objetivo, base_fecha=date(2025, 1, 2), base_numero=1):
    if fecha_objetivo < base_fecha:
        raise ValueError("Fecha anterior a la base.")
    actual = base_fecha
    numero_boc = base_numero
    while actual < fecha_objetivo:
        if actual.weekday() < 5:
            numero_boc += 1
        actual += timedelta(days=1)
    if fecha_objetivo.weekday() >= 5:
        while fecha_objetivo.weekday() >= 5:
            fecha_objetivo -= timedelta(days=1)
        return calcular_numero_boc(fecha_objetivo, base_fecha, base_numero)
    return numero_boc

def extraer_bloques_sumario(lineas):
    patron = re.compile(r'^\d{6}\s+.+')
    bloques = []
    bloque_actual = ""
    for linea in lineas:
        linea = linea.strip()
        if patron.match(linea):
            if bloque_actual:
                bloques.append(bloque_actual.strip())
            bloque_actual = linea
        else:
            if bloque_actual:
                bloque_actual += " " + linea
    if bloque_actual:
        bloques.append(bloque_actual.strip())
    return bloques

# ---------------- OBTENCIÓN DE DOCUMENTOS ---------------- #

def obtener_documentos():
    feed = feedparser.parse('https://www.boe.es/rss/boe.php')
    documentos = []
    for entry in feed.entries:
        try:
            fecha_pub = date_parser.parse(entry.published).astimezone(pytz.timezone("Europe/Madrid")).date()
        except:
            continue
        if fecha_pub == hoy:
            texto = normalizar(entry.title + " " + entry.get("description", ""))
            if any(k in texto for k in keywords_normalizadas):
                documentos.append({
                    "boletin": "BOE",
                    "titulo": entry.title,
                    "url": entry.link,
                    "fecha": fecha_pub.strftime('%Y-%m-%d'),
                    "resumen": entry.get("description", "")
                })
    return documentos

def obtener_documentos_boc_pdf():
    documentos = []
    for offset in range(-2, 3):
        fecha_prueba = hoy + timedelta(days=offset)
        try:
            numero = calcular_numero_boc(fecha_prueba)
            url_pdf = f"https://sede.gobiernodecanarias.org/boc/boc-s-{anio_actual}-{numero}.pdf"
            res = requests.get(url_pdf, timeout=10)
            res.raise_for_status()
            if not res.content.startswith(b"%PDF"):
                continue
            doc = fitz.open(stream=res.content, filetype="pdf")
            bloques = [b[4].strip().replace("\n", " ") for p in doc for b in p.get_text("blocks") if len(b[4].strip()) >= 30]
            for texto in bloques:
                if any(kw in normalizar(texto) for kw in keywords_normalizadas):
                    documentos.append({
                        "boletin": "BOC",
                        "titulo": texto[:200].upper(),
                        "url": url_pdf,
                        "fecha": fecha_prueba.strftime('%Y-%m-%d'),
                        "resumen": "(Extraído de PDF)"
                    })
            if documentos:
                break
        except:
            continue
    return documentos

def obtener_documentos_bop(nombre_bop, base_url, max_paginas, usar_ceros):
    documentos = []
    for i in range(5):
        fecha = hoy + timedelta(days=i)
        d = f"{fecha.day:02d}" if usar_ceros else str(fecha.day)
        m = str(fecha.month)
        a = str(fecha.year)[-2:]
        carpeta = f"{d}-{m}-{a}"
        url_pdf = f"{base_url}/{fecha.year}/{carpeta}/{carpeta}.pdf"
        try:
            res = requests.get(url_pdf, timeout=10)
            res.raise_for_status()
            doc = fitz.open(stream=res.content, filetype="pdf")
            texto = "\n".join([
                re.sub(r'\s+', ' ', doc[j].get_text("text").strip())
                for j in range(min(max_paginas, len(doc)))
            ])
            bloques = extraer_bloques_sumario(texto.splitlines())
            for bloque in bloques:
                if any(k in normalizar(bloque) for k in keywords_normalizadas):
                    documentos.append({
                        "boletin": nombre_bop,
                        "titulo": bloque[:200].upper(),
                        "url": url_pdf,
                        "fecha": fecha.strftime('%Y-%m-%d'),
                        "resumen": "(Sumario completo)"
                    })
            break
        except:
            continue
    return documentos

# ---------------- INTERFAZ STREAMLIT ---------------- #
st.title("📰 Buscador en boletines oficiales [BOE, BOC, BOP LP/SCTF]")

entrada_keywords = st.text_input(
    "Introduce palabras clave separadas por comas:",
    placeholder="Ejemplo: urbanismo, planeamiento, evaluación ambiental"
)

if st.button("🔍 Buscar boletines relevantes") and entrada_keywords.strip():
    entrada_normalizada = [
        ''.join(c for c in unicodedata.normalize('NFKD', kw.strip()) if not unicodedata.combining(c)).lower()
        for kw in entrada_keywords.split(",") if kw.strip()
    ]

    documentos = []
    documentos += obtener_documentos()
    documentos += obtener_documentos_boc_pdf()
    documentos += obtener_documentos_bop("BOP LP", "https://www.boplaspalmas.net/boletines", 3, usar_ceros=True)
    documentos += obtener_documentos_bop("BOP SCTF", "https://www.bopsantacruzdetenerife.es/boletines", 4, usar_ceros=False)

    # Filtrado final por las keywords introducidas por el usuario
    documentos_filtrados = [
        doc for doc in documentos
        if any(k in normalizar(doc["titulo"] + " " + doc["resumen"]) for k in entrada_normalizada)
    ]

    if documentos_filtrados:
        df = pd.DataFrame(documentos_filtrados)
        st.success(f"✅ {len(df)} documento(s) encontrados con las palabras clave proporcionadas.")
        st.dataframe(df)

        csv = df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("📥 Descargar CSV", csv, "boletines.csv", "text/csv")
    else:
        st.warning("📭 No se encontraron publicaciones relevantes con esas palabras clave.")
elif st.button("🔍 Buscar boletines relevantes"):
    st.warning("Por favor, introduce al menos una palabra clave.")
