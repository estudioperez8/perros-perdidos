import io
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


# --- BASE DE DATOS CON MIGRACIÓN AUTOMÁTICA ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='perros'")
    existe_tabla = cursor.fetchone() is not None

    if existe_tabla:
        cursor.execute("PRAGMA table_info(perros)")
        columnas = [col[1] for col in cursor.fetchall()]
        if "foto_bytes" not in columnas or "tipo_reporte" not in columnas:
            cursor.execute("DROP TABLE perros")
            existe_tabla = False

    if not existe_tabla:
        cursor.execute("""
            CREATE TABLE perros (
                id TEXT PRIMARY KEY,
                tipo_reporte TEXT,
                nombre TEXT,
                raza TEXT,
                tamanio TEXT,
                color TEXT,
                zona TEXT,
                contacto TEXT,
                fecha TEXT,
                descripcion TEXT,
                foto_bytes BLOB
            )
        """)

    conn.commit()
    conn.close()


init_db()


def procesar_foto(raw_bytes):
    """Normaliza cualquier imagen subida a bytes JPEG limpios."""
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


def extraer_vector_visual(foto_bytes):
    """Genera un vector normalizado de 8x8 RGB (192 valores) para comparar similitud visual."""
    if not foto_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(bytes(foto_bytes)))
        img = ImageOps.exif_transpose(img).convert("RGB").resize((8, 8))
        pixels = list(img.getdata())
        vec = []
        for r, g, b in pixels:
            vec.extend([r / 255.0, g / 255.0, b / 255.0])
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            return None
        return [x / norm for x in vec]
    except Exception:
        return None


def similitud_visual(foto_a, foto_b):
    """Devuelve similitud visual entre 0.0 y 1.0 usando similitud coseno sobre grilla 8x8."""
    va = extraer_vector_visual(foto_a)
    vb = extraer_vector_visual(foto_b)
    if not va or not vb:
        return None
    score = sum(a * b for a, b in zip(va, vb))
    return max(0.0, min(1.0, score))


def tokenizar(texto):
    if not texto:
        return set()
    return {t for t in re.findall(r"[a-záéíóúüñ0-9]+", texto.lower()) if len(t) >= 3}


def guardar_registro(tipo_reporte, nombre, raza, tamanio, color, zona, contacto, fecha, descripcion, foto_bytes):
    perro_id = str(uuid.uuid4())[:8]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO perros (
            id, tipo_reporte, nombre, raza, tamanio, color, zona, contacto, fecha, descripcion, foto_bytes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            perro_id,
            tipo_reporte,
            nombre.strip(),
            raza.strip(),
            tamanio,
            color.strip(),
            zona.strip(),
            contacto.strip(),
            str(fecha),
            descripcion.strip(),
            sqlite3.Binary(foto_bytes) if foto_bytes is not None else None,
        ),
    )
    conn.commit()
    conn.close()
    return perro_id


def comparar_con_base(tipo_opuesto, zona, color, tamanio, raza, descripcion, foto_bytes):
    """Compara datos y foto contra todos los registros del grupo opuesto en la base de datos."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM perros WHERE tipo_reporte = ? ORDER BY fecha DESC", (tipo_opuesto,))
    candidatos = cursor.fetchall()
    conn.close()

    zona_q = zona.strip().lower()
    color_q = color.strip().lower()
    tokens_desc = tokenizar(f"{raza} {descripcion} {color}")

    resultados = []
    for row in candidatos:
        r_id, r_tipo, r_nombre, r_raza, r_tam, r_color, r_zona, r_cont, r_fecha, r_desc, r_foto = row

        puntos = 0.0
        max_puntos = 0.0
        motivos = []

        if zona_q:
            max_puntos += 35.0
            if r_zona and (zona_q in r_zona.lower() or r_zona.lower() in zona_q):
                puntos += 35.0
                motivos.append(f"Zona: {r_zona}")

        if color_q:
            max_puntos += 25.0
            if r_color and (color_q in r_color.lower() or r_color.lower() in color_q):
                puntos += 25.0
                motivos.append(f"Color: {r_color}")

        if tamanio and tamanio != "No sé / No especificado":
            max_puntos += 15.0
            if r_tam == tamanio:
                puntos += 15.0
                motivos.append(f"Tamaño: {r_tam}")

        if tokens_desc:
            max_puntos += 15.0
            tokens_cand = tokenizar(f"{r_raza} {r_desc} {r_color}")
            comunes = tokens_desc.intersection(tokens_cand)
            if comunes:
                ratio = min(1.0, len(comunes) / max(1, min(len(tokens_desc), 3)))
                puntos += 15.0 * ratio
                motivos.append(f"Detalles ({', '.join(sorted(comunes))})")

        sim_img = similitud_visual(foto_bytes, r_foto)
        if sim_img is not None:
            max_puntos += 35.0
            puntos += 35.0 * sim_img
            motivos.append(f"Similitud de foto: {int(round(sim_img * 100))}%")

        if max_puntos > 0:
            porcentaje = int(round((puntos / max_puntos) * 100))
        else:
            porcentaje = 50
            motivos.append("Registro disponible en base")

        # Mostramos coincidencias relevantes (>= 35%) o todos si no hubo filtros específicos
        if porcentaje >= 35 or max_puntos == 0:
            resultados.append((row, porcentaje, motivos))

    resultados.sort(key=lambda item: item[1], reverse=True)
    return resultados


def sonar_campanita():
    """Reproduce un sonido suave de campanita al encontrar coincidencias."""
    components.html(
        """
        <script>
        (function() {
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (!AudioCtx) return;
                const ctx = new AudioCtx();
                const now = ctx.currentTime;

                function nota(freq, start, duration, gainVal) {
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = "sine";
                    osc.frequency.setValueAtTime(freq, start);
                    gain.gain.setValueAtTime(0.0001, start);
                    gain.gain.exponentialRampToValueAtTime(gainVal, start + 0.02);
                    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start(start);
                    osc.stop(start + duration + 0.02);
                }

                // Campanita doble armoniosa
                nota(1046.5, now, 0.45, 0.14);
                nota(1567.98, now + 0.14, 0.55, 0.10);
            } catch (e) {}
        })();
        </script>
        """,
        height=0,
    )


def mostrar_resultados(titulo, resultados, etiqueta_contacto):
    st.markdown("---")
    st.subheader(titulo)

    if not resultados:
        st.info("No se encontraron coincidencias por ahora. Tu registro quedó guardado en la base de datos para futuras comparaciones.")
        return

    sonar_campanita()
    st.success(f"🔔 ¡Coincidencias encontradas! Se detectaron {len(resultados)} perro(s) con similitud en la base de datos.")

    for row, porcentaje, motivos in resultados:
        r_id, r_tipo, r_nombre, r_raza, r_tam, r_color, r_zona, r_cont, r_fecha, r_desc, r_foto = row
        with st.container(border=True):
            col_img, col_info = st.columns([1, 2.6])
            with col_img:
                if r_foto:
                    st.image(bytes(r_foto), use_container_width=True)
                else:
                    st.caption("Sin foto cargada")
            with col_info:
                st.markdown(f"### Coincidencia: {porcentaje}%")
                if motivos:
                    st.caption("Criterios: " + " | ".join(motivos))
                st.markdown(f"**Nombre:** {r_nombre if r_nombre else 'Sin nombre'} | **Raza:** {r_raza if r_raza else 'No especificada'}")
                st.markdown(f"**Tamaño:** {r_tam} | **Color:** {r_color if r_color else 'No especificado'}")
                st.markdown(f"**Zona:** {r_zona} | **Fecha:** {r_fecha}")
                if r_desc:
                    st.markdown(f"**Señas / Detalles:** {r_desc}")
                st.markdown(f"**📞 {etiqueta_contacto}:** `{r_cont}`")


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
        cursor.execute("SELECT * FROM perros ORDER BY fecha DESC")
        registros = cursor.fetchall()
        conn.close()

        st.markdown(f"**Total de registros en base de datos:** {len(registros)}")
        for row in registros:
            r_id, r_tipo, r_nombre, r_raza, r_tam, r_color, r_zona, r_cont, r_fecha, r_desc, r_foto = row
            with st.expander(f"[{r_tipo}] {r_nombre or 'Sin nombre'} - {r_zona} ({r_fecha}) | ID: {r_id}"):
                c1, c2 = st.columns([1, 2])
                with c1:
                    if r_foto:
                        st.image(bytes(r_foto), use_container_width=True)
                    else:
                        st.caption("Sin foto")
                with c2:
                    st.write(f"**Tipo:** {r_tipo}")
                    st.write(f"**Nombre:** {r_nombre or '-'}")
                    st.write(f"**Raza:** {r_raza or '-'}")
                    st.write(f"**Tamaño:** {r_tam}")
                    st.write(f"**Color:** {r_color or '-'}")
                    st.write(f"**Zona:** {r_zona}")
                    st.write(f"**Fecha:** {r_fecha}")
                    st.write(f"**Descripción:** {r_desc or '-'}")
                    st.write(f"**Contacto:** {r_cont}")
                    if st.button("Eliminar registro", key=f"borrar_{r_id}"):
                        conn = sqlite3.connect(DB_PATH)
                        cur = conn.cursor()
                        cur.execute("DELETE FROM perros WHERE id = ?", (r_id,))
                        conn.commit()
                        conn.close()
                        st.rerun()

# --- PANTALLA PRINCIPAL: 2 OPCIONES ---
else:
    st.markdown("<h1 style='text-align: center;'>🐾 Perros Perdidos y Encontrados</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Elegí una opción para cargar foto y datos y cruzar información:</p>", unsafe_allow_html=True)

    col_op1, col_op2 = st.columns(2)
    with col_op1:
        with st.container(border=True):
            st.markdown("### ¿Perdiste a tu perro?")
            st.write("Cargá la foto y los datos de tu perro perdido y comparalos con perros vistos o encontrados.")
            if st.button("Entrar: Perdiste a tu perro", use_container_width=True, type="primary"):
                st.session_state["pantalla_activa"] = "perdido"
                st.rerun()

    with col_op2:
        with st.container(border=True):
            st.markdown("### ¿Viste un perro perdido o lo encontraste?")
            st.write("Cargá la foto y los datos del perro que viste o encontraste y comparalos con perros perdidos.")
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
            guardar_btn = st.form_submit_button("Guardar y comparar con vistos / encontrados")

        if guardar_btn:
            if not zona.strip() or not contacto.strip():
                st.error("Completá al menos **Barrio o zona** y **Teléfono / WhatsApp de contacto**.")
            else:
                try:
                    foto_final = foto_p_guardada
                    guardar_registro(
                        tipo_reporte="Perdido",
                        nombre=nombre,
                        raza=raza,
                        tamanio=tamanio,
                        color=color,
                        zona=zona,
                        contacto=contacto,
                        fecha=fecha,
                        descripcion=descripcion,
                        foto_bytes=foto_final,
                    )
                    st.session_state["foto_perdido_bytes"] = None
                    st.success("Tu perro perdido quedó guardado en la base de datos.")
                    cruces = comparar_con_base("Visto / Encontrado", zona, color, tamanio, raza, descripcion, foto_final)
                    mostrar_resultados(
                        "🔔 Coincidencias en perros VISTOS o ENCONTRADOS",
                        cruces,
                        "Contacto de quien lo vio / encontró",
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
            "Cargá la foto del perro que viste o encontraste",
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
                zona = st.text_input("Barrio o zona donde lo viste / encontraste *")
                contacto = st.text_input("Tu teléfono / WhatsApp de contacto *")

            fecha = st.date_input("Fecha", value=date.today())
            descripcion = st.text_area("Señas particulares, collar, comportamiento o lugar exacto")
            cruzar_btn = st.form_submit_button("Guardar y comparar con perros perdidos")

        if cruzar_btn:
            if not zona.strip() or not contacto.strip():
                st.error("Completá al menos **Barrio o zona** y **Tu teléfono / WhatsApp de contacto**.")
            else:
                try:
                    foto_final = foto_v_guardada
                    desc_completa = f"[{situacion}] {descripcion}".strip()
                    guardar_registro(
                        tipo_reporte="Visto / Encontrado",
                        nombre="",
                        raza=raza,
                        tamanio=tamanio,
                        color=color,
                        zona=zona,
                        contacto=contacto,
                        fecha=fecha,
                        descripcion=desc_completa,
                        foto_bytes=foto_final,
                    )
                    st.session_state["foto_visto_bytes"] = None
                    st.success("Tu reporte quedó guardado en la base de datos.")
                    cruces = comparar_con_base("Perdido", zona, color, tamanio, raza, desc_completa, foto_final)
                    mostrar_resultados(
                        "🔔 Coincidencias en PERROS PERDIDOS",
                        cruces,
                        "Contacto del dueño",
                    )
                except sqlite3.Error as e:
                    st.error(f"Error de base de datos SQLite al guardar: {e}")