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
os.makedirs(IMG_DIR, exist_ok=True)

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS perros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            estado TEXT,
            raza TEXT,
            tamano TEXT,
            color TEXT,
            sexo TEXT,
            zona TEXT,
            fecha TEXT,
            descripcion TEXT,
            contacto TEXT,
            ruta_foto TEXT
        )
    """)
    conn.commit()
    conn.close()

def guardar_perro(datos):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO perros (
            nombre, estado, raza, tamano, color, sexo, zona, fecha, descripcion, contacto, ruta_foto
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, datos)
    conn.commit()
    conn.close()

def buscar_perros(estado, tamano, color, zona, texto_libre):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    query = "SELECT * FROM perros WHERE 1=1"
    params = []

    if estado != "Todos":
        query += " AND estado = ?"
        params.append(estado)
    if tamano != "Todos":
        query += " AND tamano = ?"
        params.append(tamano)
    if color.strip():
        query += " AND LOWER(color) LIKE ?"
        params.append(f"%{color.strip().lower()}%")
    if zona.strip():
        query += " AND LOWER(zona) LIKE ?"
        params.append(f"%{zona.strip().lower()}%")
    if texto_libre.strip():
        query += " AND (LOWER(nombre) LIKE ? OR LOWER(raza) LIKE ? OR LOWER(descripcion) LIKE ?)"
        term = f"%{texto_libre.strip().lower()}%"
        params.extend([term, term, term])

    query += " ORDER BY id DESC"
    c.execute(query, params)
    resultados = c.fetchall()
    conn.close()
    return resultados

init_db()

# --- INTERFAZ ---
st.title("🐾 Registro y Buscador de Perros Perdidos")

tab_buscar, tab_cargar = st.tabs(["🔍 Buscar Perros", "➕ Publicar Aviso"])

# === PESTAÑA 1: BUSCADOR ===
with tab_buscar:
    st.subheader("Filtrar por características")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        f_estado = st.selectbox("Estado", ["Todos", "Perdido", "Encontrado"])
    with col2:
        f_tamano = st.selectbox("Tamaño", ["Todos", "Chico", "Mediano", "Grande"])
    with col3:
        f_color = st.text_input("Color (ej. negro, marrón, blanco)")
    with col4:
        f_zona = st.text_input("Barrio / Zona")

    f_texto = st.text_input("Búsqueda general (nombre, raza, collar, señas particulares...)")

    resultados = buscar_perros(f_estado, f_tamano, f_color, f_zona, f_texto)

    st.markdown(f"**Resultados encontrados:** {len(resultados)}")
    st.divider()

    if not resultados:
        st.info("No se encontraron publicaciones con esos filtros.")
    else:
        cols = st.columns(3)
        for idx, perro in enumerate(resultados):
            (p_id, nombre, estado, raza, tamano, color, sexo, zona, fecha, desc, contacto, ruta_foto) = perro
            
            with cols[idx % 3]:
                with st.container(border=True):
                    if ruta_foto and os.path.exists(ruta_foto):
                        st.image(ruta_foto, use_container_width=True)
                    
                    badge = "🔴 PERDIDO" if estado == "Perdido" else "🟢 ENCONTRADO"
                    st.markdown(f"### {badge} - {nombre or 'Sin nombre'}")
                    st.write(f"**Zona:** {zona} | **Fecha:** {fecha}")
                    st.write(f"**Características:** {tamano} • {color} • {sexo} • {raza}")
                    if desc:
                        st.caption(desc)
                    st.success(f"📞 Contacto: {contacto}")

# === PESTAÑA 2: CARGAR DATOS Y FOTO ===
with tab_cargar:
    st.subheader("Cargar datos del perro")
    
    with st.form("form_perro", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            estado = st.selectbox("Tipo de aviso *", ["Perdido", "Encontrado"])
            nombre = st.text_input("Nombre (si se conoce)")
            raza = st.text_input("Raza o mestizo", value="Mestizo")
            tamano = st.selectbox("Tamaño *", ["Chico", "Mediano", "Grande"])
            color = st.text_input("Color principal y manchas *")
        
        with c2:
            sexo = st.selectbox("Sexo", ["Macho", "Hembra", "No sé"])
            zona = st.text_input("Barrio / Calle de referencia *")
            fecha = st.date_input("Fecha *", value=date.today())
            contacto = st.text_input("Teléfono / WhatsApp de contacto *")
            foto = st.file_uploader("Subir foto del perro *", type=["jpg", "jpeg", "png", "webp"])

        descripcion = st.text_area("Señas particulares (collar, cicatrices, comportamiento, etc.)")
        
        submitted = st.form_submit_button("Publicar aviso", type="primary")

        if submitted:
            if not color or not zona or not contacto or not foto:
                st.error("Completá todos los campos obligatorios marcados con * y subí una foto.")
            else:
                # Guardar imagen con nombre único
                ext = foto.name.split(".")[-1]
                nombre_archivo = f"{uuid.uuid4().hex}.{ext}"
                ruta_guardado = os.path.join(IMG_DIR, nombre_archivo)
                
                img = Image.open(foto)
                img.save(ruta_guardado)

                guardar_perro((
                    nombre.strip(),
                    estado,
                    raza.strip(),
                    tamano,
                    color.strip(),
                    sexo,
                    zona.strip(),
                    str(fecha),
                    descripcion.strip(),
                    contacto.strip(),
                    ruta_guardado
                ))
                st.success("¡Aviso publicado correctamente! Ya aparece en la pestaña de búsqueda.")