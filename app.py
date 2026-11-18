import os
import sqlite3
import uuid
from datetime import date
import streamlit as st
from PIL import Image

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Buscador de Perros Perdidos", page_icon="🐾", layout="wide")

# Rutas absolutas para evitar problemas en Streamlit Cloud
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "perros.db")
IMG_DIR = os.path.join(BASE_DIR, "fotos_perros")

if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR, exist_ok=True)

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS perros (
            id TEXT PRIMARY KEY,
            estado TEXT,
            nombre TEXT,
            raza TEXT,
            tamanio TEXT,
            color TEXT,
            zona TEXT,
            contacto TEXT,
            fecha TEXT,
            descripcion TEXT,
            foto_path TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- INTERFAZ PRINCIPAL ---
st.markdown("<h1 style='text-align: center; color: #FF4B4B;'>🐾 Registro y Buscador de Perros Perdidos</h1>", unsafe_allow_html=True)

menu = ["Cargue su perro perdido", "Busque si su perro fue visto", "Panel de Administrador"]
choice = st.sidebar.selectbox("Menú de Navegación", menu)

# --- SECCIÓN 1: CARGUE SU PERRO PERDIDO ---
if choice == "Cargue su perro perdido":
    st.subheader("📢 Registrar un perro que se extravió")
    st.markdown("Complete los datos de su mascota y suba una foto obligatoria o recomendada para que quede registrada en la base de datos.")
    
    # Subida de foto fuera del formulario
    st.markdown("### 📸 Fotografía del perro")
    foto_subida = st.file_uploader(
        "Seleccioná o arrastrá la foto desde la galería", 
        type=["jpg", "jpeg", "png", "webp", "heic"]
    )
    
    if foto_subida is not None:
        st.image(foto_subida, width=250, caption="Vista previa de la foto seleccionada")

    with st.form("form_perro_perdido"):
        col1, col2 = st.columns(2)
        with col1:
            estado = "Se busca"
            nombre = st.text_input("Nombre del perro")
            raza = st.text_input("Raza aproximada")
        with col2:
            tamanio = st.selectbox("Tamaño", ["Pequeño", "Mediano", "Grande"])
            color = st.text_input("Color principal (ej. Negro con pecho blanco)")
            zona = st.text_input("Barrio o Zona donde se perdió")
        
        contacto = st.text_input("Teléfono / WhatsApp de contacto")
        fecha = st.date_input("Fecha de extravío", value=date.today())
        descripcion = st.text_area("Señas particulares (collar, mancha en la pata, herida, etc.)")
        
        submit_btn = st.form_submit_button("💾 Guardar en la Base de Datos")

    if submit_btn:
        if not zona or not contacto:
            st.error("Por favor completa al menos la **Zona** y el **Contacto** para poder guardar el aviso.")
        else:
            perro_id = str(uuid.uuid4())[:8]
            foto_path = ""
            
            # Guardado físico robusto usando bytes directos
            if foto_subida is not None:
                try:
                    ext = foto_subida.name.split(".")[-1].lower()
                    foto_nombre = f"{perro_id}.{ext}"
                    foto_path = os.path.join(IMG_DIR, foto_nombre)
                    
                    with open(foto_path, "wb") as f:
                        f.write(foto_subida.getbuffer())
                except Exception as e:
                    st.error(f"Error detallado al guardar la imagen: {e}")
                    foto_path = ""
                
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO perros VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                perro_id, estado, nombre, raza, tamanio, color, zona, contacto, 
                str(fecha), descripcion, foto_path
            ))
            conn.commit()
            conn.close()
            
            st.success("¡Su perro perdido fue registrado y guardado con éxito con su foto en la base de datos!")

# --- SECCIÓN 2: BUSQUE SI SU PERRO FUE VISTO ---
elif choice == "Busque si su perro fue visto":
    st.subheader("🔍 Busque y compare si un perro visto coincide con los perdidos")
    st.markdown("Ingrese las características o suba la foto del perro que encontró para compararlo automáticamente con los reportes de perros perdidos.")
    
    foto_busqueda = st.file_uploader(
        "Suba la foto del perro encontrado para comparar", 
        type=["jpg", "jpeg", "png", "webp", "heic"]
    )
    if foto_busqueda is not None:
        st.image(foto_busqueda, width=250, caption="Perro visto / encontrado")

    with st.form("form_buscar_visto"):
        col1, col2 = st.columns(2)
        with col1:
            filtro_zona = st.text_input("Barrio / Zona donde lo encontró o vio")
            filtro_tamanio = st.selectbox("Tamaño", ["Todos", "Pequeño", "Mediano", "Grande"])
        with col2:
            filtro_color = st.text_input("Color principal (ej. marrón, negro)")
            contacto_buscador = st.text_input("Su teléfono de contacto (por si hay coincidencia)")
            
        buscar_btn = st.form_submit_button("🔎 Comparar y Buscar Coincidencias")

    if buscar_btn:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM perros WHERE estado = 'Se busca'")
        todos_perdidos = cursor.fetchall()
        conn.close()

        coincidencias = []
        for p in todos_perdidos:
            r_id, r_estado, r_nombre, r_raza, r_tamanio, r_color, r_zona, r_contacto, r_fecha, r_desc, r_foto = p
            
            match = True
            if filtro_zona and filtro_zona.lower() not in r_zona.lower():
                match = False
            if filtro_color and filtro_color.lower() not in r_color.lower():
                match = False
            if filtro_tamanio != "Todos" and r_tamanio != filtro_tamanio:
                match = False
                
            if match:
                coincidencias.append(p)

        st.markdown("---")
        if coincidencias:
            st.warning(f"⚠️ ¡Atención! Encontramos **{len(coincidencias)} posibles coincidencias** en la base de perros perdidos:")
            for c in coincidencias:
                cols_c = st.columns([1, 3])
                with cols_c[0]:
                    if c[10] and os.path.exists(c[10]):
                        st.image(c[10], width=140)
                    else:
                        st.warning("Sin foto registrada")
                with cols_c[1]:
                    st.markdown(f"**Nombre:** {c[2] if c[2] else 'Sin nombre'} | **Raza:** {c[3]}")
                    st.markdown(f"**Zona:** 📍 {c[6]} | **Tamaño:** {c[4]} | **Color:** {c[5]}")
                    st.markdown(f"**Descripción:** {c[9]}")
                    st.markdown(f"📞 **Contacto del dueño:** `{c[7]}`")
                    st.markdown("---")
        else:
            st.info("No se encontraron coincidencias exactas con los filtros ingresados en los perros perdidos actuales.")

# --- SECCIÓN 3: PANEL DE ADMINISTRADOR ---
elif choice == "Panel de Administrador":
    st.subheader("🔐 Panel de Control de Administrador")
    
    ADMIN_USER = "admin2026"
    ADMIN_PASS = "2026"

    usuario_ingresado = st.text_input("Usuario administrador")
    password_ingresado = st.text_input("Contraseña", type="password")

    if st.button("Iniciar Sesión"):
        if usuario_ingresado == ADMIN_USER and password_ingresado == ADMIN_PASS:
            st.session_state["is_admin"] = True
            st.success("¡Acceso concedido!")
        else:
            st.error("Usuario o contraseña incorrectos.")

    if st.session_state.get("is_admin", False):
        st.markdown("---")
        st.markdown("### 🗄️ Base de Datos Completa (Fotos y Características)")
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM perros ORDER BY fecha DESC")
        registros = cursor.fetchall()
        
        st.write(f"Total de registros guardados: **{len(registros)}**")

        if not registros:
            st.info("Aún no hay registros en la base de datos.")
        else:
            for reg in registros:
                r_id, r_estado, r_nombre, r_raza, r_tamanio, r_color, r_zona, r_contacto, r_fecha, r_desc, r_foto = reg
                with st.expander(f"ID: {r_id} | [{r_estado}] - {r_zona} ({r_fecha})"):
                    col_a, col_b = st.columns([1, 2])
                    with col_a:
                        # Verificación robusta de existencia de archivo físico
                        if r_foto and os.path.exists(r_foto):
                            st.image(r_foto, width=160)
                        else:
                            st.write(f"⚠️ Sin foto o archivo no hallado en ruta: {r_foto}")
                    with col_b:
                        st.markdown(f"**Estado:** {r_estado}")
                        st.markdown(f"**Nombre:** {r_nombre if r_nombre else 'No especificado'}")
                        st.markdown(f"**Raza:** {r_raza if r_raza else 'No especificada'}")
                        st.markdown(f"**Tamaño:** {r_tamanio} | **Color:** {r_color}")
                        st.markdown(f"**Zona:** 📍 {r_zona}")
                        st.markdown(f"**Fecha:** {r_fecha}")
                        st.markdown(f"**Descripción:** {r_desc if r_desc else 'Sin descripción'}")
                        st.markdown(f"📞 **Contacto:** `{r_contacto}`")
                        
                        if st.button(f"🗑️ Eliminar registro {r_id}", key=f"del_{r_id}"):
                            cursor.execute("DELETE FROM perros WHERE id = ?", (r_id,))
                            conn.commit()
                            if r_foto and os.path.exists(r_foto):
                                try:
                                    os.remove(r_foto)
                                except:
                                    pass
                            st.success(f"Registro {r_id} eliminado con éxito.")
                            st.rerun()
        conn.close()
        
        if st.button("Cerrar Sesión"):
            st.session_state["is_admin"] = False
            st.rerun()
            