import io
import json
import math
import os
import re
import sqlite3
import uuid
from datetime import date
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageOps

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Perros Perdidos", page_icon="🐾", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "perros.db")

ADMIN_USER = "admin2026"
ADMIN_PASS = "2026"


# --- BASE DE DATOS CON COLUMNAS SEPARADAS: PERROS PERDIDOS Y PERROS VISTOS ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
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


def procesar_foto(raw_bytes):
    """Convierte cualquier imagen a bytes JPEG normalizados."""
    if not raw_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((1200, 1200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return raw_bytes


def extraer_descriptores_imagen(foto_bytes):
    """
    Extrae un vector combinado de color/estructura (16x16 RGB) y luminancia normalizada
    para comparar similitud visual entre dos fotos de perros.
    """
    if not foto_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(bytes(foto_bytes)))
        img = ImageOps.exif_transpose(img).convert("RGB").resize((16, 16))
        pixels = list(img.getdata())

        rgb_vec = []
        gray_vec = []
        for r, g, b in pixels:
            rgb_vec.extend([r / 255.0, g / 255.0, b / 255.0])
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            gray_vec.append(lum)

        # Normalización de luminancia (media 0, norma 1) para tolerar cambios de luz
        mean_g = sum(gray_vec) / len(gray_vec)
        gray_centered = [x - mean_g for x in gray_vec]

        norm_rgb = math.sqrt(sum(x * x for x in rgb_vec))
        norm_gray = math.sqrt(sum(x * x for x in gray_centered))
        if norm_rgb == 0 or norm_gray == 0:
            return None

        return ([x / norm_rgb for x in rgb_vec], [x / norm_gray for x in gray_centered])
    except Exception:
        return None


def calcular_similitud_imagen(foto_a, foto_b):
    """Retorna porcentaje (0 a 100) o None si alguna foto no existe."""
    desc_a = extraer_descriptores_imagen(foto_a)
    desc_b = extraer_descriptores_imagen(foto_b)
    if not desc_a or not desc_b:
        return None

    rgb_a, gray_a = desc_a
    rgb_b, gray_b = desc_b

    sim_rgb = max(0.0, min(1.0, sum(x * y for x, y in zip(rgb_a, rgb_b))))
    sim_gray = max(0.0, min(1.0, (sum(x * y for x, y in zip(gray_a, gray_b)) + 1.0) / 2.0))

    # Priorizamos similitud cromática + estructura/luminancia
    combinada = (0.65 * sim_rgb) + (0.35 * sim_gray)
    return int(round(combinada * 100))


def tokenizar(texto):
    if not texto:
        return set()
    return {t for t in re.findall(r"[a-záéíóúüñ0-9]+", texto.lower()) if len(t) >= 3}


def guardar_en_columna(columna_destino, datos_dict, foto_bytes):
    """
    Guarda en la columna 'perro_perdido' + 'foto_perdido' o en 'perro_visto' + 'foto_visto'.
    """
    reg_id = str(uuid.uuid4())[:8]
    datos_json = json.dumps(datos_dict, ensure_ascii=False)
    blob = sqlite3.Binary(foto_bytes) if foto_bytes is not None else None

    conn = sqlite3.connect(DB_PATH)
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
    """
    Compara los datos y especialmente la imagen contra todos los registros
    almacenados en la columna opuesta ('perro_visto' o 'perro_perdido').
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if columna_opuesta == "visto":
        cursor.execute("SELECT id, fecha_registro, perro_visto, foto_visto FROM perros WHERE perro_visto IS NOT NULL")
    else:
        cursor.execute("SELECT id, fecha_registro, perro_perdido, foto_perdido FROM perros WHERE perro_perdido IS NOT NULL")

    filas = cursor.fetchall()
    conn.close()

    zona_n = (datos_nuevo.get("zona") or "").strip().lower()
    color_n = (datos_nuevo.get("color") or "").strip().lower()
    tam_n = datos_nuevo.get("tamanio") or ""
    tokens_n = tokenizar(f"{datos_nuevo.get('raza', '')} {datos_nuevo.get('color', '')} {datos_nuevo.get('descripcion', '')}")

    coincidencias = []
    for reg_id, fecha_reg, datos_raw, foto_cand in filas:
        try:
            datos_c = json.loads(datos_raw) if datos_raw else {}
        except Exception:
            datos_c = {}

        sim_img = calcular_similitud_imagen(foto_nueva, foto_cand)

        # Puntaje de datos (0 a 100)
        puntos_datos = 0.0
        peso_datos = 0.0
        motivos = []

        zona_c = (datos_c.get("zona") or "").strip().lower()
        color_c = (datos_c.get("color") or "").strip().lower()
        tam_c = datos_c.get("tamanio") or ""
        tokens_c = tokenizar(f"{datos_c.get('raza', '')} {datos_c.get('color', '')} {datos_c.get('descripcion', '')}")

        if zona_n and zona_c:
            peso_datos += 40.0
            if zona_n in zona_c or zona_c in zona_n:
                puntos_datos += 40.0
                motivos.append(f"Zona: {datos_c.get('zona')}")

        if color_n and color_c:
            peso_datos += 35.0
            if color_n in color_c or color_c in color_n:
                puntos_datos += 35.0
                motivos.append(f"Color: {datos_c.get('color')}")

        if tam_n and tam_n != "No sé / No especificado" and tam_c and tam_c != "No sé / No especificado":
            peso_datos += 15.0
            if tam_n == tam_c:
                puntos_datos += 15.0
                motivos.append(f"Tamaño: {tam_c}")

        if tokens_n and tokens_c:
            peso_datos += 10.0
            comunes = tokens_n.intersection(tokens_c)
            if comunes:
                puntos_datos += 10.0 * min(1.0, len(comunes) / max(1, min(len(tokens_n), 2)))
                motivos.append(f"Detalles: {', '.join(sorted(comunes))}")

        score_datos = int(round((puntos_datos / peso_datos) * 100)) if peso_datos > 0 else None

        # Priorizamos fuertemente la imagen (70% imagen + 30% datos cuando hay foto en ambos lados)
        if sim_img is not None and score_datos is not None:
            score_total = int(round((0.70 * sim_img) + (0.30 * score_datos)))
            motivos.insert(0, f"Imagen: {sim_img}%")
        elif sim_img is not None:
            score_total = sim_img
            motivos.insert(0, f"Imagen: {sim_img}%")
        elif score_datos is not None:
            score_total = score_datos
        else:
            score_total = 50
            motivos.append("Registro disponible")

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
    return coincidencias


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
        with st.container(border=True):
            col_img, col_info = st.columns([1, 2.6])
            with col_img:
                if item["foto"]:
                    st.image(bytes(item["foto"]), use_container_width=True)
                else:
                    st.caption("Sin foto cargada")
            with col_info:
                img_txt = f" | Similitud de imagen: **{item['sim_img']}%**" if item["sim_img"] is not None else ""
                st.markdown(f"### Coincidencia general: {item['score']}%{img_txt}")
                if item["motivos"]:
                    st.caption("Detalle: " + " • ".join(item["motivos"]))
                if d.get("nombre"):
                    st.markdown(f"**Nombre:** {d.get('nombre')}")
                st.markdown(f"**Raza:** {d.get('raza') or 'No especificada'} | **Tamaño:** {d.get('tamanio') or '-'} | **Color:** {d.get('color') or '-'}")
                st.markdown(f"**Zona:** {d.get('zona') or '-'} | **Fecha:** {d.get('fecha') or item['fecha_registro']}")
                if d.get("descripcion"):
                    st.markdown(f"**Señas / Detalles:** {d.get('descripcion')}")
                st.markdown(f"**📞 {etiqueta_contacto}:** `{d.get('contacto') or 'No cargado'}`")


# --- ESTADO ---
if "pantalla_activa" not in st.session_state:
    st.session_state["pantalla_activa"] = None
if "foto_perdido_bytes" not in st.session_state:
    st.session_state["foto_perdido_bytes"] = None
if "foto_visto_bytes" not in st.session_state:
    st.session_state["foto_visto_bytes"] = None

st.sidebar.title("Menú")
modo_sidebar = st.sidebar.radio("Ir a:", ["Inicio (2 opciones)", "Administrador"])

# --- MODO ADMINISTRADOR ---
if modo_sidebar == "Administrador":
    st.title("Panel de Administrador")

    if not st.session_state.get("is_admin", False):
        with st.form("form_login_admin"):
            u = st.text_input("Usuario")
            p = st.text_input("Contraseña", type="password")
            entrar = st.form_submit_button("Ingresar")
        if entrar:
            if u == ADMIN_USER and p == ADMIN_PASS:
                st.session_state["is_admin"] = True
                st.rerun()
            else:
                st.error("Credenciales incorrectas.")
    else:
        col_top1, col_top2 = st.columns([3, 1])
        with col_top1:
            st.success("Sesión iniciada como administrador.")
        with col_top2:
            if st.button("Cerrar sesión"):
                st.session_state["is_admin"] = False
                st.rerun()

        conn = sqlite3.connect(DB_PATH)
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
            with st.expander(f"[{etiqueta}] {datos_ref.get('nombre') or datos_ref.get('raza') or 'Sin título'} - {datos_ref.get('zona') or '-'} ({fecha_reg}) | ID: {reg_id}"):
                c_perd, c_vist = st.columns(2)
                with c_perd:
                    st.markdown("**Columna Perro Perdido**")
                    if p_perd:
                        if f_perd:
                            st.image(bytes(f_perd), width=180)
                        for k, v in p_perd.items():
                            st.write(f"- **{k}:** {v or '-'}")
                    else:
                        st.caption("Vacío en este registro")
                with c_vist:
                    st.markdown("**Columna Perro Visto**")
                    if p_vist:
                        if f_vist:
                            st.image(bytes(f_vist), width=180)
                        for k, v in p_vist.items():
                            st.write(f"- **{k}:** {v or '-'}")
                    else:
                        st.caption("Vacío en este registro")
                if st.button("Eliminar registro", key=f"borrar_{reg_id}"):
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    cur.execute("DELETE FROM perros WHERE id = ?", (reg_id,))
                    conn.commit()
                    conn.close()
                    st.rerun()

# --- PANTALLA PRINCIPAL: 2 OPCIONES ---
else:
    st.markdown("<h1 style='text-align: center;'>🐾 Perros Perdidos y Vistos</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Elegí una opción para cargar foto y datos y comparar imágenes:</p>", unsafe_allow_html=True)

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
            "Cargá la foto de tu perro perdido",
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
                nombre = st.text_input("Nombre del perro")
                raza = st.text_input("Raza")
                tamanio = st.selectbox("Tamaño", ["No sé / No especificado", "Pequeño", "Mediano", "Grande"])
            with c2:
                color = st.text_input("Color / Pelaje")
                zona = st.text_input("Barrio o zona donde se perdió *")
                contacto = st.text_input("Teléfono / WhatsApp de contacto *")

            fecha = st.date_input("Fecha en que se perdió", value=date.today())
            descripcion = st.text_area("Señas particulares, collar, edad aproximada o detalles")
            guardar_btn = st.form_submit_button("Guardar y comparar imagen con perros vistos")

        if guardar_btn:
            if not zona.strip() or not contacto.strip():
                st.error("Completá al menos **Barrio o zona** y **Teléfono / WhatsApp de contacto**.")
            else:
                try:
                    datos_perdido = {
                        "nombre": nombre.strip(),
                        "raza": raza.strip(),
                        "tamanio": tamanio,
                        "color": color.strip(),
                        "zona": zona.strip(),
                        "contacto": contacto.strip(),
                        "fecha": str(fecha),
                        "descripcion": descripcion.strip(),
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
            "Cargá la foto del perro visto",
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
                raza = st.text_input("Raza aproximada")
                tamanio = st.selectbox("Tamaño", ["No sé / No especificado", "Pequeño", "Mediano", "Grande"])
            with c2:
                color = st.text_input("Color / Pelaje")
                zona = st.text_input("Barrio o zona donde lo viste *")
                contacto = st.text_input("Tu teléfono / WhatsApp de contacto *")

            fecha = st.date_input("Fecha", value=date.today())
            descripcion = st.text_area("Señas particulares, collar, comportamiento o lugar exacto")
            cruzar_btn = st.form_submit_button("Guardar y comparar imagen con perros perdidos")

        if cruzar_btn:
            if not zona.strip() or not contacto.strip():
                st.error("Completá al menos **Barrio o zona** y **Tu teléfono / WhatsApp de contacto**.")
            else:
                try:
                    datos_visto = {
                        "situacion": situacion,
                        "raza": raza.strip(),
                        "tamanio": tamanio,
                        "color": color.strip(),
                        "zona": zona.strip(),
                        "contacto": contacto.strip(),
                        "fecha": str(fecha),
                        "descripcion": descripcion.strip(),
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