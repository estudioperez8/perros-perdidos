import html
import io
import json
import math
import os
import re
import sqlite3
import time
import uuid
from datetime import date
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageFilter, ImageOps

# --- CONFIGURACIÓN INICIAL Y SEGURIDAD ---
st.set_page_config(page_title="Perros Perdidos", page_icon="🐾", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "perros.db")

MAX_FILE_BYTES = 6 * 1024 * 1024  # 6 MB máximo por foto
MAX_RESULTADOS = 15
MAX_INTENTOS_LOGIN = 5
BLOQUEO_SEGUNDOS = 60
UMBRAL_BASE_COINCIDENCIA = 82  # Base desde 82%

Image.MAX_IMAGE_PIXELS = 20_000_000  # Previene bombas de descompresión en imágenes gigantes

try:
    ADMIN_USER = str(st.secrets["ADMIN_USER"])
except Exception:
    ADMIN_USER = os.getenv("ADMIN_USER", "admin2026")

try:
    ADMIN_PASS = str(st.secrets["ADMIN_PASS"])
except Exception:
    ADMIN_PASS = os.getenv("ADMIN_PASS", "2026")


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


# --- BASE DE DATOS CON COLUMNAS SEPARADAS: PERROS PERDIDOS Y PERROS VISTOS ---
def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='perros'")
    existe_tabla = cursor.fetchone() is not None

    if existe_tabla:
        cursor.execute("PRAGMA table_info(perros)")
        columnas = {col[1] for col in cursor.fetchall()}
        requeridas = {"perro_perdido", "foto_perdido", "perro_visto", "foto_visto"}
        if not requeridas.issubset(columnas):
            cursor.execute("DROP TABLE perros")
            existe_tabla = False

    if not existe_tabla:
        cursor.execute("""
            CREATE TABLE perros (
                id TEXT PRIMARY KEY,
                fecha_registro TEXT,
                perro_perdido TEXT,
                foto_perdido BLOB,
                perro_visto TEXT,
                foto_visto BLOB
            )
        """)

    conn.commit()
    conn.close()


init_db()


def limpiar_texto(valor, max_len=300):
    if not valor:
        return ""
    limpio = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(valor)).strip()
    return limpio[:max_len]


def procesar_foto(raw_bytes):
    """Valida tamaño y convierte la imagen a JPEG limpio."""
    if not raw_bytes:
        return None
    if len(raw_bytes) > MAX_FILE_BYTES:
        st.warning("La imagen supera el límite de 6 MB. Elegí una foto más liviana.")
        return None
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        ancho, alto = img.size
        if ancho <= 0 or alto <= 0 or (ancho * alto) > Image.MAX_IMAGE_PIXELS:
            st.warning("Las dimensiones de la imagen no son válidas o son demasiado grandes.")
            return None
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((1200, 1200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        st.warning("No se pudo procesar la imagen seleccionada. Probá con otro archivo JPG, PNG o WEBP.")
        return None


def _recorte_central(img, margen=0.15):
    """Recorta levemente los bordes externos para priorizar el cuerpo/cabeza del perro."""
    w, h = img.size
    left = int(w * margen)
    top = int(h * margen)
    right = max(left + 1, int(w * (1.0 - margen)))
    bottom = max(top + 1, int(h * (1.0 - margen)))
    return img.crop((left, top, right, bottom))


def _similitud_histograma(h1, h2):
    """Intersección normalizada entre dos histogramas de igual longitud (0.0 a 1.0)."""
    if not h1 or not h2 or len(h1) != len(h2):
        return 0.0
    s1 = sum(h1)
    s2 = sum(h2)
    if s1 <= 0 or s2 <= 0:
        return 0.0
    n1 = [x / s1 for x in h1]
    n2 = [x / s2 for x in h2]
    return max(0.0, min(1.0, sum(min(a, b) for a, b in zip(n1, n2))))


def _similitud_vector_centrado(v1, v2):
    """Similitud coseno entre vectores normalizados (0.0 a 1.0)."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0 or n2 == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (n1 * n2)))


def extraer_descriptores_imagen(foto_bytes):
    """
    Extrae descriptores enfocados en:
    1) Color del pelaje: histograma RGB cuantizado (8x8x8) y distribución de tonos claros/oscuros.
    2) Forma y contorno del animal: grilla espacial 12x12 de forma/bordes con peso central.
    """
    if not foto_bytes:
        return None
    try:
        base = Image.open(io.BytesIO(bytes(foto_bytes)))
        base = ImageOps.exif_transpose(base).convert("RGB")
        sujeto_rgb = _recorte_central(base, margen=0.14)

        # --- 1. COLOR DEL PELAJE ---
        color_img = sujeto_rgb.resize((96, 96))
        hist_rgb = [0] * (8 * 8 * 8)
        tonos_claros_oscuros = [0, 0, 0]  # oscuro (<85), medio (85..170), claro (>170)

        for r, g, b in color_img.getdata():
            rb = min(7, r // 32)
            gb = min(7, g // 32)
            bb = min(7, b // 32)
            hist_rgb[(rb * 64) + (gb * 8) + bb] += 1

            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if lum < 85:
                tonos_claros_oscuros[0] += 1
            elif lum <= 170:
                tonos_claros_oscuros[1] += 1
            else:
                tonos_claros_oscuros[2] += 1

        # --- 2. FORMA Y CONTORNO DEL ANIMAL ---
        # Normalizamos tamaño para comparar estructura/forma con independencia de resolución
        forma_rgb = sujeto_rgb.resize((120, 120))
        gray_img = forma_rgb.convert("L")
        edges_img = gray_img.filter(ImageFilter.FIND_EDGES)

        # Combinamos silueta (luminancia suavizada) + bordes/forma del cuerpo
        grid_size = 12
        cell_w = 120 // grid_size
        cell_h = 120 // grid_size
        gray_px = list(gray_img.getdata())
        edge_px = list(edges_img.getdata())

        forma_vec = []
        for gy in range(grid_size):
            for gx in range(grid_size):
                # Peso mayor hacia el centro de la grilla (donde suele ubicarse el perro)
                dy = (gy - (grid_size - 1) / 2.0) / ((grid_size - 1) / 2.0)
                dx = (gx - (grid_size - 1) / 2.0) / ((grid_size - 1) / 2.0)
                peso_espacial = max(0.35, 1.15 - 0.45 * math.sqrt(dx * dx + dy * dy))

                suma_forma = 0.0
                for py in range(gy * cell_h, (gy + 1) * cell_h):
                    row_off = py * 120
                    for px in range(gx * cell_w, (gx + 1) * cell_w):
                        idx = row_off + px
                        g_val = gray_px[idx] / 255.0
                        e_val = edge_px[idx] / 255.0
                        # Resalta contornos y estructura interna del pelaje/forma
                        suma_forma += (0.55 * e_val) + (0.45 * abs(g_val - 0.5))

                promedio_celda = (suma_forma / (cell_w * cell_h)) * peso_espacial
                forma_vec.append(promedio_celda)

        # Proporción de aspecto normalizada (ancho/alto del recorte)
        w_s, h_s = sujeto_rgb.size
        ratio_aspecto = min(2.0, max(0.5, w_s / max(1, h_s)))

        return {
            "hist_rgb": hist_rgb,
            "tonos": tonos_claros_oscuros,
            "forma_vec": forma_vec,
            "ratio": ratio_aspecto,
        }
    except Exception:
        return None


def calcular_similitud_imagen(foto_a, foto_b):
    """
    Retorna porcentaje (0 a 100) o None si alguna foto no existe.
    Pondera color del pelaje (45%) y forma/contorno del animal (55%).
    """
    desc_a = extraer_descriptores_imagen(foto_a)
    desc_b = extraer_descriptores_imagen(foto_b)
    if not desc_a or not desc_b:
        return None

    sim_hist_color = _similitud_histograma(desc_a["hist_rgb"], desc_b["hist_rgb"])
    sim_tonos = _similitud_histograma(desc_a["tonos"], desc_b["tonos"])
    sim_color = (0.75 * sim_hist_color) + (0.25 * sim_tonos)

    sim_grilla_forma = _similitud_vector_centrado(desc_a["forma_vec"], desc_b["forma_vec"])
    diff_ratio = abs(desc_a["ratio"] - desc_b["ratio"])
    sim_proporcion = max(0.0, 1.0 - (diff_ratio / 1.5))
    sim_forma = (0.80 * sim_grilla_forma) + (0.20 * sim_proporcion)

    # Curva suave para que similitudes reales de color + forma se reflejen con claridad
    combinada = (0.45 * sim_color) + (0.55 * sim_forma)
    ajustada = combinada ** 0.85
    return int(round(max(0.0, min(1.0, ajustada)) * 100))


def tokenizar(texto):
    if not texto:
        return set()
    return {t for t in re.findall(r"[a-záéíóúüñ0-9]+", texto.lower()) if len(t) >= 3}


def calcular_score_par(datos_a, foto_a, datos_b, foto_b):
    """Calcula el porcentaje de coincidencia general (0 a 100) entre dos registros."""
    sim_img = calcular_similitud_imagen(foto_a, foto_b)

    zona_a = (datos_a.get("zona") or "").strip().lower()
    color_a = (datos_a.get("color") or "").strip().lower()
    tam_a = datos_a.get("tamanio") or ""
    tokens_a = tokenizar(f"{datos_a.get('raza', '')} {datos_a.get('color', '')} {datos_a.get('descripcion', '')}")

    zona_b = (datos_b.get("zona") or "").strip().lower()
    color_b = (datos_b.get("color") or "").strip().lower()
    tam_b = datos_b.get("tamanio") or ""
    tokens_b = tokenizar(f"{datos_b.get('raza', '')} {datos_b.get('color', '')} {datos_b.get('descripcion', '')}")

    puntos_datos = 0.0
    peso_datos = 0.0
    motivos = []

    if zona_a and zona_b:
        peso_datos += 40.0
        if zona_a in zona_b or zona_b in zona_a:
            puntos_datos += 40.0
            motivos.append(f"Zona: {datos_b.get('zona')}")

    if color_a and color_b:
        peso_datos += 35.0
        if color_a in color_b or color_b in color_a:
            puntos_datos += 35.0
            motivos.append(f"Color: {datos_b.get('color')}")

    if tam_a and tam_a != "No sé / No especificado" and tam_b and tam_b != "No sé / No especificado":
        peso_datos += 15.0
        if tam_a == tam_b:
            puntos_datos += 15.0
            motivos.append(f"Tamaño: {tam_b}")

    if tokens_a and tokens_b:
        peso_datos += 10.0
        comunes = tokens_a.intersection(tokens_b)
        if comunes:
            puntos_datos += 10.0 * min(1.0, len(comunes) / max(1, min(len(tokens_a), 2)))
            motivos.append(f"Detalles: {', '.join(sorted(comunes))}")

    score_datos = int(round((puntos_datos / peso_datos) * 100)) if peso_datos > 0 else None

    if sim_img is not None and score_datos is not None:
        score_total = int(round((0.75 * sim_img) + (0.25 * score_datos)))
        motivos.insert(0, f"Color y forma: {sim_img}%")
    elif sim_img is not None:
        score_total = sim_img
        motivos.insert(0, f"Color y forma: {sim_img}%")
    elif score_datos is not None:
        score_total = score_datos
    else:
        score_total = 50
        motivos.append("Registro disponible")

    return score_total, sim_img, motivos


def guardar_en_columna(columna_destino, datos_dict, foto_bytes):
    """Guarda en la columna perro_perdido/foto_perdido o perro_visto/foto_visto."""
    reg_id = str(uuid.uuid4())[:8]
    datos_json = json.dumps(datos_dict, ensure_ascii=False)
    blob = sqlite3.Binary(foto_bytes) if foto_bytes is not None else None

    conn = get_conn()
    cursor = conn.cursor()

    if columna_destino == "perdido":
        cursor.execute(
            """
            INSERT INTO perros (id, fecha_registro, perro_perdido, foto_perdido, perro_visto, foto_visto)
            VALUES (?, ?, ?, ?, NULL, NULL)
            """,
            (reg_id, str(date.today()), datos_json, blob),
        )
    else:
        cursor.execute(
            """
            INSERT INTO perros (id, fecha_registro, perro_perdido, foto_perdido, perro_visto, foto_visto)
            VALUES (?, ?, NULL, NULL, ?, ?)
            """,
            (reg_id, str(date.today()), datos_json, blob),
        )

    conn.commit()
    conn.close()
    return reg_id


def comparar_contra_columna_opuesta(columna_opuesta, datos_nuevo, foto_nueva):
    """Compara datos y especialmente color/forma de la imagen contra la columna opuesta."""
    conn = get_conn()
    cursor = conn.cursor()

    if columna_opuesta == "visto":
        cursor.execute("SELECT id, fecha_registro, perro_visto, foto_visto FROM perros WHERE perro_visto IS NOT NULL")
    else:
        cursor.execute("SELECT id, fecha_registro, perro_perdido, foto_perdido FROM perros WHERE perro_perdido IS NOT NULL")

    filas = cursor.fetchall()
    conn.close()

    coincidencias = []
    for reg_id, fecha_reg, datos_raw, foto_cand in filas:
        try:
            datos_c = json.loads(datos_raw) if datos_raw else {}
        except Exception:
            datos_c = {}

        score_total, sim_img, motivos = calcular_score_par(datos_nuevo, foto_nueva, datos_c, foto_cand)

        if score_total >= 45 or (sim_img is not None and sim_img >= 55):
            coincidencias.append(
                {
                    "id": reg_id,
                    "fecha_registro": fecha_reg,
                    "datos": datos_c,
                    "foto": foto_cand,
                    "score": score_total,
                    "sim_img": sim_img,
                    "motivos": motivos,
                }
            )

    coincidencias.sort(key=lambda x: (x["sim_img"] if x["sim_img"] is not None else -1, x["score"]), reverse=True)
    return coincidencias[:MAX_RESULTADOS]


def contar_coincidencias_base_82():
    """Cuenta cuántos pares entre perros perdidos y perros vistos alcanzan la base del 82%."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT perro_perdido, foto_perdido FROM perros WHERE perro_perdido IS NOT NULL")
    perdidos = cursor.fetchall()
    cursor.execute("SELECT perro_visto, foto_visto FROM perros WHERE perro_visto IS NOT NULL")
    vistos = cursor.fetchall()
    conn.close()

    if not perdidos or not vistos:
        return 0

    total = 0
    for p_raw, f_perd in perdidos:
        try:
            datos_p = json.loads(p_raw) if p_raw else {}
        except Exception:
            datos_p = {}

        for v_raw, f_vist in vistos:
            try:
                datos_v = json.loads(v_raw) if v_raw else {}
            except Exception:
                datos_v = {}

            score_total, _, _ = calcular_score_par(datos_p, f_perd, datos_v, f_vist)
            if score_total >= UMBRAL_BASE_COINCIDENCIA:
                total += 1

    return total


def sonar_campanita():
    """Reproduce un sonido de campanita en el navegador cuando hay coincidencias."""
    components.html(
        """
        <script>
        (function() {
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (!AudioCtx) return;
                const ctx = new AudioCtx();
                const now = ctx.currentTime;

                function campana(freq, start, dur, vol) {
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = "sine";
                    osc.frequency.setValueAtTime(freq, start);
                    gain.gain.setValueAtTime(0.0001, start);
                    gain.gain.exponentialRampToValueAtTime(vol, start + 0.015);
                    gain.gain.exponentialRampToValueAtTime(0.0001, start + dur);
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start(start);
                    osc.stop(start + dur + 0.02);
                }

                campana(1174.66, now, 0.5, 0.16);
                campana(1760.0, now + 0.15, 0.6, 0.11);
            } catch (e) {}
        })();
        </script>
        """,
        height=0,
    )


def mostrar_coincidencias(titulo, coincidencias, etiqueta_contacto):
    st.markdown("---")
    st.subheader(titulo)

    if not coincidencias:
        st.info("No se encontraron coincidencias por ahora. Tu registro quedó guardado en su columna correspondiente para futuras comparaciones.")
        return

    sonar_campanita()
    st.success(f"🔔 ¡Coincidencias detectadas! Se encontraron {len(coincidencias)} perro(s) similares.")

    for item in coincidencias:
        d = item["datos"]
        nombre_seguro = html.escape(str(d.get("nombre") or "Sin nombre"))
        raza_segura = html.escape(str(d.get("raza") or "No especificada"))
        tam_seguro = html.escape(str(d.get("tamanio") or "-"))
        color_seguro = html.escape(str(d.get("color") or "-"))
        zona_segura = html.escape(str(d.get("zona") or "-"))
        fecha_segura = html.escape(str(d.get("fecha") or item["fecha_registro"]))
        desc_segura = html.escape(str(d.get("descripcion") or ""))
        contacto_seguro = html.escape(str(d.get("contacto") or "No cargado"))

        with st.container(border=True):
            col_img, col_info = st.columns([1, 2.6])
            with col_img:
                if item["foto"]:
                    st.image(bytes(item["foto"]), use_container_width=True)
                else:
                    st.caption("Sin foto cargada")
            with col_info:
                img_txt = f" | Similitud de color y forma: **{item['sim_img']}%**" if item["sim_img"] is not None else ""
                st.markdown(f"### Coincidencia general: {item['score']}%{img_txt}")
                if item["motivos"]:
                    st.caption("Detalle: " + " • ".join(item["motivos"]))
                if d.get("nombre"):
                    st.markdown(f"**Nombre:** {nombre_seguro}")
                st.markdown(f"**Raza:** {raza_segura} | **Tamaño:** {tam_seguro} | **Color:** {color_seguro}")
                st.markdown(f"**Zona:** {zona_segura} | **Fecha:** {fecha_segura}")
                if desc_segura:
                    st.markdown(f"**Señas / Detalles:** {desc_segura}")
                st.markdown(f"**📞 {html.escape(etiqueta_contacto)}:** `{contacto_seguro}`")


def render_footer_principal():
    """Pie de página en la página principal con 'created by Jumpy' y carita de perro con gorrito de Santa Claus."""
    st.markdown("---")
    st.markdown(
        """
        <div style="display: flex; align-items: center; justify-content: center; gap: 10px; padding: 14px 0 6px 0; color: #555;">
            <svg width="36" height="36" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-label="Perro con gorrito de Santa Claus">
                <!-- Orejas -->
                <ellipse cx="14" cy="34" rx="7" ry="13" transform="rotate(15 14 34)" fill="#8D5524"/>
                <ellipse cx="50" cy="34" rx="7" ry="13" transform="rotate(-15 50 34)" fill="#8D5524"/>
                <!-- Cara del perro -->
                <ellipse cx="32" cy="36" rx="18" ry="15" fill="#C68642"/>
                <ellipse cx="32" cy="41" rx="10" ry="8" fill="#F5E6D3"/>
                <!-- Ojos -->
                <circle cx="25" cy="33" r="2.6" fill="#1E1E1E"/>
                <circle cx="39" cy="33" r="2.6" fill="#1E1E1E"/>
                <circle cx="24.2" cy="32.2" r="0.9" fill="#FFFFFF"/>
                <circle cx="38.2" cy="32.2" r="0.9" fill="#FFFFFF"/>
                <!-- Nariz y boca -->
                <ellipse cx="32" cy="39" rx="3.4" ry="2.4" fill="#1E1E1E"/>
                <path d="M28 43 Q32 46.5 36 43" stroke="#1E1E1E" stroke-width="2" fill="none" stroke-linecap="round"/>
                <!-- Gorrito de Santa Claus -->
                <path d="M16 25 Q32 6 49 23 L45 27 Q32 14 19 27 Z" fill="#D92626"/>
                <rect x="15" y="23" width="34" height="6" rx="3" fill="#FFFFFF"/>
                <circle cx="49" cy="23" r="4.5" fill="#FFFFFF"/>
            </svg>
            <span style="font-size: 0.95rem; font-weight: 500;">created by Jumpy</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


# --- ESTADO ---
if "pantalla_activa" not in st.session_state:
    st.session_state["pantalla_activa"] = None
if "foto_perdido_bytes" not in st.session_state:
    st.session_state["foto_perdido_bytes"] = None
if "foto_visto_bytes" not in st.session_state:
    st.session_state["foto_visto_bytes"] = None
if "login_intentos" not in st.session_state:
    st.session_state["login_intentos"] = 0
if "login_bloqueado_hasta" not in st.session_state:
    st.session_state["login_bloqueado_hasta"] = 0.0

st.sidebar.title("Menú")
modo_sidebar = st.sidebar.radio("Ir a:", ["Inicio (2 opciones)", "Administrador"])

# --- MODO ADMINISTRADOR ---
if modo_sidebar == "Administrador":
    st.title("Panel de Administrador")

    if not st.session_state.get("is_admin", False):
        ahora = time.time()
        bloqueado_hasta = float(st.session_state.get("login_bloqueado_hasta", 0.0))
        if ahora < bloqueado_hasta:
            restante = int(math.ceil(bloqueado_hasta - ahora))
            st.error(f"Demasiados intentos fallidos. Esperá {restante} segundos para volver a intentar.")
        else:
            with st.form("form_login_admin"):
                u = st.text_input("Usuario", max_chars=80)
                p = st.text_input("Contraseña", type="password", max_chars=80)
                entrar = st.form_submit_button("Ingresar")
            if entrar:
                if u == ADMIN_USER and p == ADMIN_PASS:
                    st.session_state["is_admin"] = True
                    st.session_state["login_intentos"] = 0
                    st.session_state["login_bloqueado_hasta"] = 0.0
                    st.rerun()
                else:
                    intentos = int(st.session_state.get("login_intentos", 0)) + 1
                    st.session_state["login_intentos"] = intentos
                    if intentos >= MAX_INTENTOS_LOGIN:
                        st.session_state["login_bloqueado_hasta"] = time.time() + BLOQUEO_SEGUNDOS
                        st.session_state["login_intentos"] = 0
                        st.error(f"Credenciales incorrectas. Acceso bloqueado por {BLOQUEO_SEGUNDOS} segundos.")
                    else:
                        st.error(f"Credenciales incorrectas. Intento {intentos} de {MAX_INTENTOS_LOGIN}.")
    else:
        col_top1, col_top2 = st.columns([3, 1])
        with col_top1:
            st.success("Sesión iniciada como administrador.")
        with col_top2:
            if st.button("Cerrar sesión"):
                st.session_state["is_admin"] = False
                st.rerun()

        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT id, fecha_registro, perro_perdido, foto_perdido, perro_visto, foto_visto FROM perros ORDER BY fecha_registro DESC")
        registros = cursor.fetchall()
        conn.close()

        st.markdown(f"**Total de filas en base de datos:** {len(registros)}")
        for reg_id, fecha_reg, p_perd_raw, f_perd, p_vist_raw, f_vist in registros:
            p_perd = json.loads(p_perd_raw) if p_perd_raw else None
            p_vist = json.loads(p_vist_raw) if p_vist_raw else None
            etiqueta = "Perro Perdido" if p_perd else "Perro Visto"
            datos_ref = p_perd or p_vist or {}
            titulo_exp = f"[{etiqueta}] {datos_ref.get('nombre') or datos_ref.get('raza') or 'Sin título'} - {datos_ref.get('zona') or '-'} ({fecha_reg}) | ID: {reg_id}"
            with st.expander(titulo_exp):
                c_perd, c_vist = st.columns(2)
                with c_perd:
                    st.markdown("**Columna Perro Perdido**")
                    if p_perd:
                        if f_perd:
                            st.image(bytes(f_perd), width=180)
                        for k, v in p_perd.items():
                            st.write(f"- **{html.escape(str(k))}:** {html.escape(str(v or '-'))}")
                    else:
                        st.caption("Vacío en este registro")
                with c_vist:
                    st.markdown("**Columna Perro Visto**")
                    if p_vist:
                        if f_vist:
                            st.image(bytes(f_vist), width=180)
                        for k, v in p_vist.items():
                            st.write(f"- **{html.escape(str(k))}:** {html.escape(str(v or '-'))}")
                    else:
                        st.caption("Vacío en este registro")
                if st.button("Eliminar registro", key=f"borrar_{reg_id}"):
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute("DELETE FROM perros WHERE id = ?", (reg_id,))
                    conn.commit()
                    conn.close()
                    st.rerun()

# --- PANTALLA PRINCIPAL: 2 OPCIONES ---
else:
    st.markdown("<h1 style='text-align: center;'>🐾 Perros Perdidos y Vistos</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Elegí una opción para cargar foto y datos y comparar imágenes:</p>", unsafe_allow_html=True)

    total_coincidencias = contar_coincidencias_base_82()
    _, col_metric, _ = st.columns([1.5, 1, 1.5])
    with col_metric:
        st.metric(
            label="Coincidencias",
            value=total_coincidencias,
        )

    col_op1, col_op2 = st.columns(2)
    with col_op1:
        with st.container(border=True):
            st.markdown("### ¿Perdiste a tu perro?")
            st.write("Cargá la foto y los datos de tu perro perdido y comparalos con la columna de perros vistos.")
            if st.button("Entrar: Perdiste a tu perro", use_container_width=True, type="primary"):
                st.session_state["pantalla_activa"] = "perdido"
                st.rerun()

    with col_op2:
        with st.container(border=True):
            st.markdown("### ¿Viste un perro perdido o lo encontraste?")
            st.write("Cargá la foto y los datos del perro visto y comparalos con la columna de perros perdidos.")
            if st.button("Entrar: Viste un perro o lo encontraste", use_container_width=True):
                st.session_state["pantalla_activa"] = "visto"
                st.rerun()

    pantalla = st.session_state.get("pantalla_activa")

    # --- OPCIÓN 1: PERDISTE A TU PERRO ---
    if pantalla == "perdido":
        st.markdown("---")
        if st.button("← Volver a las 2 opciones"):
            st.session_state["pantalla_activa"] = None
            st.session_state["foto_perdido_bytes"] = None
            st.rerun()

        st.subheader("¿Perdiste a tu perro? — Cargá su foto y sus datos")

        archivo_p = st.file_uploader(
            "Cargá la foto de tu perro perdido (máx. 6 MB)",
            type=["jpg", "jpeg", "png", "webp", "heic"],
            key="uploader_perdido",
        )
        if archivo_p is not None:
            st.session_state["foto_perdido_bytes"] = procesar_foto(archivo_p.getvalue())

        foto_p_guardada = st.session_state.get("foto_perdido_bytes")
        if foto_p_guardada:
            st.image(foto_p_guardada, width=220, caption="Foto lista para guardar y comparar")

        with st.form("form_perdido"):
            c1, c2 = st.columns(2)
            with c1:
                nombre = st.text_input("Nombre del perro", max_chars=80)
                raza = st.text_input("Raza", max_chars=80)
                tamanio = st.selectbox("Tamaño", ["No sé / No especificado", "Pequeño", "Mediano", "Grande"])
            with c2:
                color = st.text_input("Color / Pelaje", max_chars=100)
                zona = st.text_input("Barrio o zona donde se perdió *", max_chars=120)
                contacto = st.text_input("Teléfono / WhatsApp de contacto *", max_chars=80)

            fecha = st.date_input("Fecha en que se perdió", value=date.today())
            descripcion = st.text_area("Señas particulares, collar, edad aproximada o detalles", max_chars=500)
            guardar_btn = st.form_submit_button("Guardar y comparar imagen con perros vistos")

        if guardar_btn:
            zona_limpia = limpiar_texto(zona, 120)
            contacto_limpio = limpiar_texto(contacto, 80)
            if not zona_limpia or not contacto_limpio:
                st.error("Completá al menos **Barrio o zona** y **Teléfono / WhatsApp de contacto**.")
            else:
                try:
                    datos_perdido = {
                        "nombre": limpiar_texto(nombre, 80),
                        "raza": limpiar_texto(raza, 80),
                        "tamanio": tamanio,
                        "color": limpiar_texto(color, 100),
                        "zona": zona_limpia,
                        "contacto": contacto_limpio,
                        "fecha": str(fecha),
                        "descripcion": limpiar_texto(descripcion, 500),
                    }
                    foto_final = foto_p_guardada
                    guardar_en_columna("perdido", datos_perdido, foto_final)
                    st.session_state["foto_perdido_bytes"] = None
                    st.success("Guardado en la columna de **Perros Perdidos**.")
                    coincidencias = comparar_contra_columna_opuesta("visto", datos_perdido, foto_final)
                    mostrar_coincidencias(
                        "🔔 Coincidencias en la columna de PERROS VISTOS",
                        coincidencias,
                        "Contacto de quien lo vio",
                    )
                except sqlite3.Error as e:
                    st.error(f"Error de base de datos SQLite al guardar: {e}")

    # --- OPCIÓN 2: VISTE UN PERRO PERDIDO O LO ENCONTRASTE ---
    elif pantalla == "visto":
        st.markdown("---")
        if st.button("← Volver a las 2 opciones"):
            st.session_state["pantalla_activa"] = None
            st.session_state["foto_visto_bytes"] = None
            st.rerun()

        st.subheader("¿Viste un perro perdido o lo encontraste? — Cargá su foto y sus datos")

        archivo_v = st.file_uploader(
            "Cargá la foto del perro visto (máx. 6 MB)",
            type=["jpg", "jpeg", "png", "webp", "heic"],
            key="uploader_visto",
        )
        if archivo_v is not None:
            st.session_state["foto_visto_bytes"] = procesar_foto(archivo_v.getvalue())

        foto_v_guardada = st.session_state.get("foto_visto_bytes")
        if foto_v_guardada:
            st.image(foto_v_guardada, width=220, caption="Foto lista para guardar y comparar")

        with st.form("form_visto"):
            c1, c2 = st.columns(2)
            with c1:
                situacion = st.selectbox("¿Lo viste o lo encontraste?", ["Visto", "Encontrado"])
                raza = st.text_input("Raza aproximada", max_chars=80)
                tamanio = st.selectbox("Tamaño", ["No sé / No especificado", "Pequeño", "Mediano", "Grande"])
            with c2:
                color = st.text_input("Color / Pelaje", max_chars=100)
                zona = st.text_input("Barrio o zona donde lo viste *", max_chars=120)
                contacto = st.text_input("Tu teléfono / WhatsApp de contacto *", max_chars=80)

            fecha = st.date_input("Fecha", value=date.today())
            descripcion = st.text_area("Señas particulares, collar, comportamiento o lugar exacto", max_chars=500)
            cruzar_btn = st.form_submit_button("Guardar y comparar imagen con perros perdidos")

        if cruzar_btn:
            zona_limpia = limpiar_texto(zona, 120)
            contacto_limpio = limpiar_texto(contacto, 80)
            if not zona_limpia or not contacto_limpio:
                st.error("Completá al menos **Barrio o zona** y **Tu teléfono / WhatsApp de contacto**.")
            else:
                try:
                    datos_visto = {
                        "situacion": situacion,
                        "raza": limpiar_texto(raza, 80),
                        "tamanio": tamanio,
                        "color": limpiar_texto(color, 100),
                        "zona": zona_limpia,
                        "contacto": contacto_limpio,
                        "fecha": str(fecha),
                        "descripcion": limpiar_texto(descripcion, 500),
                    }
                    foto_final = foto_v_guardada
                    guardar_en_columna("visto", datos_visto, foto_final)
                    st.session_state["foto_visto_bytes"] = None
                    st.success("Guardado en la columna de **Perros Vistos**.")
                    coincidencias = comparar_contra_columna_opuesta("perdido", datos_visto, foto_final)
                    mostrar_coincidencias(
                        "🔔 Coincidencias en la columna de PERROS PERDIDOS",
                        coincidencias,
                        "Contacto del dueño",
                    )
                except sqlite3.Error as e:
                    st.error(f"Error de base de datos SQLite al guardar: {e}")

    render_footer_principal()