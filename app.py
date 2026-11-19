import io
import os
import sqlite3
import uuid
from datetime import date
import streamlit as st
from PIL import Image

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Perros Perdidos", page_icon="🐾", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "perros.db")

ADMIN_USER = "admin2026"
ADMIN_PASS = "2026"


# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS perros (
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


def procesar_foto(archivo_subido):
    """Convierte cualquier imagen (jpg, png, webp, heic, etc.) a bytes JPEG limpios."""
    if archivo_subido is None:
        return None
    raw_bytes = archivo_subido.getvalue()
    if not raw_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((1200, 1200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        # Si Pillow no puede abrir un formato especial, guardamos los bytes originales
        return raw_bytes


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
            foto_bytes,
        ),
    )
    conn.commit()
    conn.close()
    return perro_id


def buscar_cruces(tipo_opuesto, zona, color, tamanio):
    """Cruza información entre 'Perdido' y 'Visto o Encontrado'."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM perros WHERE tipo_reporte = ? ORDER BY fecha DESC", (tipo_opuesto,))
    candidatos = cursor.fetchall()
    conn.close()

    zona_q = zona.strip().lower()
    color_q = color.strip().lower()

    cruces = []
    for row in candidatos:
        r_id, r_tipo, r_nombre, r_raza, r_tam, r_color, r_zona, r_cont, r_fecha, r_desc, r_foto = row
        puntaje = 0
        motivos = []

        if zona_q and r_zona and (zona_q in r_zona.lower() or r_zona.lower() in zona_q):
            puntaje += 2
            motivos.append(f"Zona coincidente ({r_zona})")

        if color_q and r_color and (color_q in r_color.lower() or r_color.lower() in color_q):
            puntaje += 2
            motivos.append(f"Color coincidente ({r_color})")

        if tamanio and tamanio != "No sé / No especificado" and r_tam == tamanio:
            puntaje += 1
            motivos.append(f"Tamaño ({r_tam})")

        # Si el usuario no cargó filtros de zona/color/tamaño, mostramos los últimos registros del tipo opuesto
        if not zona_q and not color_q and (not tamanio or tamanio == "No sé / No especificado"):
            cruces.append((row, 0, ["Registro reciente"]))
        elif puntaje > 0:
            cruces.append((row, puntaje, motivos))

    cruces.sort(key=lambda item: item[1], reverse=True)
    return cruces


def mostrar_cruces(titulo_alerta, cruces, etiqueta_contacto):
    st.markdown("---")
    st.subheader(titulo_alerta)
    if not cruces:
        st.info("Por ahora no hay registros del otro grupo que coincidan. Tu aviso ya quedó guardado para futuros cruces.")
        return

    for row, puntaje, motivos in cruces:
        r_id, r_tipo, r_nombre, r_raza, r_tam, r_color, r_zona, r_cont, r_fecha, r_desc, r_foto = row
        with st.container(border=True):
            col_img, col_info = st.columns([1, 2.5])
            with col_img:
                if r_foto:
                    st.image(r_foto, use_container_width=True)
                else:
                    st.caption("Sin foto cargada")
            with col_info:
                if puntaje > 0:
                    st.success(f"Coincidencia ({', '.join(motivos)})")
                st.markdown(f"**Nombre:** {r_nombre if r_nombre else 'Sin nombre'} | **Raza:** {r_raza if r_raza else 'No especificada'}")
                st.markdown(f"**Tamaño:** {r_tam} | **Color:** {r_color if r_color else 'No especificado'}")
                st.markdown(f"**Zona:** {r_zona} | **Fecha:** {r_fecha}")
                if r_desc:
                    st.markdown(f"**Señas / Detalles:** {r_desc}")
                st.markdown(f"**{etiqueta_contacto}:** `{r_cont}`")


# --- NAVEGACIÓN PRINCIPAL (2 OPCIONES CLARAS AL ENTRAR) ---
if "pantalla_activa" not in st.session_state:
    st.session_state["pantalla_activa"] = None

st.sidebar.title("Menú")
modo_sidebar = st.sidebar.radio(
    "Ir a:",
    ["Inicio (2 opciones)", "Administrador"],
    index=0 if st.session_state.get("modo_sidebar", "Inicio (2 opciones)") == "Inicio (2 opciones)" else 1,
)
st.session_state["modo_sidebar"] = modo_sidebar

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
                        st.image(r_foto, use_container_width=True)
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
    st.markdown("<p style='text-align: center;'>Elegí una opción para cargar datos y foto y cruzar información:</p>", unsafe_allow_html=True)

    col_op1, col_op2 = st.columns(2)
    with col_op1:
        with st.container(border=True):
            st.markdown("### ¿Perdiste a tu perro?")
            st.write("Cargá la foto y los datos de tu perro perdido para guardarlo y ver si alguien ya reportó haberlo visto o encontrado.")
            if st.button("Entrar: Perdiste a tu perro", use_container_width=True, type="primary"):
                st.session_state["pantalla_activa"] = "perdido"
                st.rerun()

    with col_op2:
        with st.container(border=True):
            st.markdown("### ¿Viste un perro perdido o lo encontraste?")
            st.write("Cargá la foto y los datos del perro que viste o encontraste para cruzarlo con los perros reportados como perdidos.")
            if st.button("Entrar: Viste un perro o lo encontraste", use_container_width=True):
                st.session_state["pantalla_activa"] = "visto"
                st.rerun()

    pantalla = st.session_state.get("pantalla_activa")

    # --- OPCIÓN 1: PERDISTE A TU PERRO ---
    if pantalla == "perdido":
        st.markdown("---")
        if st.button("← Volver a las 2 opciones"):
            st.session_state["pantalla_activa"] = None
            st.rerun()

        st.subheader("Cargar datos y foto de tu perro perdido")

        foto_perdido = st.file_uploader(
            "Foto de tu perro perdido",
            type=["jpg", "jpeg", "png", "webp", "heic"],
            key="uploader_perdido",
        )
        if foto_perdido is not None:
            st.image(foto_perdido, width=220, caption="Foto seleccionada")

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
            guardar_btn = st.form_submit_button("Guardar perro perdido y cruzar con vistos/encontrados")

        if guardar_btn:
            if not zona.strip() or not contacto.strip():
                st.error("Completá al menos **Barrio o zona** y **Teléfono / WhatsApp de contacto**.")
            else:
                foto_bytes = procesar_foto(foto_perdido)
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
                    foto_bytes=foto_bytes,
                )
                st.success("Tu perro perdido quedó guardado en la base de datos.")
                cruces = buscar_cruces("Visto / Encontrado", zona, color, tamanio)
                mostrar_cruces(
                    "Posibles coincidencias en perros VISTOS o ENCONTRADOS",
                    cruces,
                    "Contacto de quien lo vio/encontró",
                )

    # --- OPCIÓN 2: VISTE UN PERRO PERDIDO O LO ENCONTRASTE ---
    elif pantalla == "visto":
        st.markdown("---")
        if st.button("← Volver a las 2 opciones"):
            st.session_state["pantalla_activa"] = None
            st.rerun()

        st.subheader("Cargar datos y foto del perro que viste o encontraste")

        foto_visto = st.file_uploader(
            "Foto del perro que viste o encontraste",
            type=["jpg", "jpeg", "png", "webp", "heic"],
            key="uploader_visto",
        )
        if foto_visto is not None:
            st.image(foto_visto, width=220, caption="Foto seleccionada")

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
            cruzar_btn = st.form_submit_button("Guardar reporte y cruzar con perros perdidos")

        if cruzar_btn:
            if not zona.strip() or not contacto.strip():
                st.error("Completá al menos **Barrio o zona** y **Tu teléfono / WhatsApp de contacto**.")
            else:
                foto_bytes = procesar_foto(foto_visto)
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
                    foto_bytes=foto_bytes,
                )
                st.success("Tu reporte quedó guardado en la base de datos.")
                cruces = buscar_cruces("Perdido", zona, color, tamanio)
                mostrar_cruces(
                    "Posibles coincidencias en PERROS PERDIDOS",
                    cruces,
                    "Contacto del dueño",
                )