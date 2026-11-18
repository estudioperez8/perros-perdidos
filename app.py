import os
import sqlite3
import uuid
from datetime import date
import streamlit as st
from PIL import Image

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Buscador de Perros Perdidos", page_icon="🐾", layout="wide")

DB_PATH = "perros.db"
IMG_DIR = "fotos_perros"

if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR)

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

menu = ["Buscar Perros", "Publicar Aviso", "Panel de Administrador"]
choice = st.sidebar.selectbox("Menú de Navegación", menu)

# --- SECCIÓN: BUSCAR PERROS ---
if choice == "Buscar Perros":
    st.subheader("🔍 Filtrar perros perdidos o encontrados")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM perros ORDER BY fecha DESC")
    rows = cursor.fetchall()
    conn.close()

    # Filtros de búsqueda
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        filtro_estado = st.selectbox("Estado", ["Todos", "Se busca", "Encontrado / Visto"])
    with col2:
        filtro_tamanio = st.selectbox("Tamaño", ["Todos", "Pequeño", "Mediano", "Grande"])
    with col3:
        filtro_color = st.text_input("Color (ej. negro, marrón, blanco)")
    with col4:
        filtro_zona = st.text_input("Barrio / Zona")

    busqueda_general = st.text_input("Búsqueda general (nombre, raza, collar, señas particulares...)")

    perros_filtrados = []
    for row in rows:
        r_id, r_estado, r_nombre, r_raza, r_tamanio, r_color, r_zona, r_contacto, r_fecha, r_desc, r_foto = row
        
        if filtro_estado != "Todos" and r_estado != filtro_estado:
            continue
        if filtro_tamanio != "Todos" and r_tamanio != filtro_tamanio:
            continue
        if filtro_color and filtro_color.lower() not in r_color.lower():
            continue
        if filtro_zona and filtro_zona.lower() not in r_zona.lower():
            continue
        if busqueda_general:
            texto_completo = f"{r_nombre} {r_raza} {r_desc} {r_zona} {r_color}".lower()
            if busqueda_general.lower() not in texto_completo:
                continue
                
        perros_filtrados.append(row)

    st.markdown(f"**Resultados encontrados:** {len(perros_filtrados)}")
    st.markdown("---")

    if not perros_filtrados:
        st.info("No se encontraron publicaciones con esos filtros.")
    else:
        for i in range(0, len(perros_filtrados), 3):
            cols = st.columns(3)
            for j in range(3):
                if i + j < len(perros_filtrados):
                    p = perros_filtrados[i + j]
                    with cols[j]:
                        with st.container(border=True):
                            st.markdown(f"### **{p[1]}**")
                            if p[10] and os.path.exists(p[10]):
                                st.image(p[10], use_column_width=True)
                            else:
                                st.warning("Sin imagen disponible")
                            
                            st.markdown(f"**Nombre:** {p[2] if p[2] else 'Desconocido'}")
                            st.markdown(f"**Raza:** {p[3] if p[3] else 'No especificada'}")
                            st.markdown(f"**Tamaño:** {p[4]} | **Color:** {p[5]}")
                            st.markdown(f"**Zona:** 📍 {p[6]}")
                            st.markdown(f"**Fecha:** {p[8]}")
                            if p[9]:
                                st.markdown(f"*Señas:* {p[9]}")
                            st.markdown(f"📞 **Contacto:** `{p[7]}`")

# --- SECCIÓN: PUBLICAR AVISO (DATOS PRIMERO, FOTO MULTIFORMATO AL FINAL Y BOTÓN DE GUARDADO) ---
elif choice == "Publicar Aviso":
    st.subheader("📢 Publicar un perro perdido o encontrado")
    
    with st.form("form_publicar"):
        st.markdown("### 1️⃣ Completá los datos del perro")
        col1, col2 = st.columns(2)
        with col1:
            estado = st.selectbox("¿Qué situación es?", ["Se busca", "Encontrado / Visto"])
            nombre = st.text_input("Nombre del perro (si lo sabes)")
            raza = st.text_input("Raza aproximada")
        with col2:
            tamanio = st.selectbox("Tamaño", ["Pequeño", "Mediano", "Grande"])
            color = st.text_input("Color principal (ej. Negro con pecho blanco)")
            zona = st.text_input("Barrio o Zona aproximada")
        
        contacto = st.text_input("Teléfono / WhatsApp de contacto")
        fecha = st.date_input("Fecha del hecho", value=date.today())
        descripcion = st.text_area("Señas particulares (collar, mancha en la pata, herida, etc.)")
        
        st.markdown("---")
        st.markdown("### 2️⃣ Subí la fotografía (Múltiples formatos aceptados)")
        foto_subida = st.file_uploader(
            "Seleccioná o arrastrá la foto desde la galería", 
            type=["jpg", "jpeg", "png", "webp", "heic"]
        )
        
        st.markdown("---")
        submit_btn = st.form_submit_button("💾 Guardar en la Base y Comparar Coincidencias")

    if submit_btn:
        if not zona or not contacto or not foto_subida:
            st.error("Por favor completa la Zona, el Contacto y sube una Foto antes de guardar.")
        else:
            perro_id = str(uuid.uuid4())[:8]
            ext = foto_subida.name.split(".")[-1].lower()
            foto_nombre = f"{perro_id}.{ext}"
            foto_path = os.path.join(IMG_DIR, foto_nombre)
            
            with open(foto_path, "wb") as f:
                f.write(foto_subida.getbuffer())
                
            # Guardar en Base de Datos
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO perros VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                perro_id, estado, nombre, raza, tamanio, color, zona, contacto, 
                str(fecha), descripcion, foto_path
            ))
            conn.commit()
            
            # COMPARAR CON REGISTROS EXISTENTES EN LA BASE
            cursor.execute("SELECT * FROM perros WHERE id != ? AND (zona LIKE ? OR color LIKE ?)", 
                           (perro_id, f"%{zona}%", f"%{color}%"))
            coincidencias = cursor.fetchall()
            conn.close()
            
            st.success("¡Aviso guardado correctamente en la base de datos!")
            
            if coincidencias:
                st.warning(f"⚠️ ¡Atención! Encontramos **{len(coincidencias)} coincidencias posibles** en la base de datos por zona o características similares:")
                for c in coincidencias:
                    cols_c = st.columns([1, 3])
                    with cols_c[0]:
                        if c[10] and os.path.exists(c[10]):
                            st.image(c[10], width=100)
                    with cols_c[1]:
                        st.markdown(f"**Estado:** {c[1]} | **Zona:** {c[6]}")
                        st.markdown(f"**Descripción:** {c[9]}")
                        st.markdown(f"📞 Contacto: `{c[7]}`")
                        st.markdown("---")

# --- SECCIÓN: PANEL DE ADMINISTRADOR (EXCLUSIVO) ---
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
                        if r_foto and os.path.exists(r_foto):
                            st.image(r_foto, width=150)
                        else:
                            st.write("Sin foto disponible")
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
                                os.remove(r_foto)
                            st.success(f"Registro {r_id} eliminado con éxito.")
                            st.rerun()
        conn.close()
        
        if st.button("Cerrar Sesión"):
            st.session_state["is_admin"] = False
            st.rerun()