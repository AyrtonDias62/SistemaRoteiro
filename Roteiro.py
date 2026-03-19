import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from datetime import datetime
import math
import base64
from PIL import Image
import io

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Roteirizador Tecnolab",
    layout="wide",
    page_icon="🚚"
)

# --- 2. FUNÇÕES DE SUPORTE (IMAGEM E COORDENADAS) ---
def get_image_base64(path):
    try:
        with Image.open(path) as img:
            img = img.convert("RGBA")
            with io.BytesIO() as buffer:
                img.save(buffer, format="PNG")
                img_str = base64.b64encode(buffer.getvalue()).decode()
                return f"data:image/png;base64,{img_str}"
    except:
        return None

def calcular_distancia_reta(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return round(R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a))), 2)

def get_coords_cep(cep, client_ors):
    r = requests.get(f"https://viacep.com.br/ws/{cep.replace('-','')}/json/").json()
    if "erro" in r: return None
    logra, bairro, cidade = r.get('logradouro', 'N/A'), r.get('bairro', 'N/A'), r.get('localidade', 'N/A')
    
    # Busca com foco em SBC/SP
    geo = client_ors.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
    if geo and len(geo['features']) > 0:
        c = geo['features'][0]['geometry']['coordinates']
        lat, lon = c[1], c[0]
    else:
        geo_cep = client_ors.pelias_search(text=f"{cep}, Brasil", size=1)
        c = geo_cep['features'][0]['geometry']['coordinates']
        lat, lon = c[1], c[0]
    
    # Trava de segurança para evitar cidades a 700km
    if calcular_distancia_reta(lat, lon, -23.6912, -46.5594) > 150:
        geo_fix = client_ors.pelias_search(text=f"{cep}, Brasil", size=1)
        c = geo_fix['features'][0]['geometry']['coordinates']
        lat, lon = c[1], c[0]
        
    return {"lat": lat, "lon": lon, "endereco": f"{logra}, {bairro}"}

# --- 3. CARREGAMENTO DE ASSETS E API ---
img_b64 = get_image_base64("furgao_tecnolab3.png")

try:
    api_key = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=api_key)
except Exception as e:
    st.error("Erro: Configure a ORS_KEY nas Secrets do Streamlit.")
    st.stop()

# Base de Unidades
unidades = [
    {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594},
    {"nome": "Tecno U2", "lat": -23.70601, "lon": -46.54946},
    {"nome": "Tecno U4", "lat": -23.709069, "lon": -46.413002},
    {"nome": "Tecno U5", "lat": -23.65458, "lon": -46.53554},
    {"nome": "Tecno U13", "lat": -23.68791, "lon": -46.62192},
]

if "resultado_rota" not in st.session_state:
    st.session_state.resultado_rota = None

# --- 4. INTERFACE VISUAL (TÍTULO COMPACTO) ---
if img_b64:
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 10px;">
            <img src="{img_b64}" height="35">
            <h2 style="color: #2E86C1; margin: 0;">Roteirizador Tecnolab</h2>
        </div>
        """, unsafe_allow_html=True
    )
else:
    st.title("Roteirizador Tecnolab")

st.divider()

# --- 5. BARRA LATERAL (ENTRADA) ---
with st.sidebar:
    st.header("📍 Itinerário")
    ceps_input = []
    for i in range(5):
        c = st.text_input(f"CEP Parada {i+1}:", key=f"cep_input_{i}")
        if c: ceps_input.append(c)
    
    btn_calc = st.button("Calcular Rota Otimizada", use_container_width=True)

if btn_calc and ceps_input:
    with st.spinner("Otimizando trajeto..."):
        destinos = []
        for cp in ceps_input:
            info = get_coords_cep(cp, ors_client)
            if info: destinos.append(info)
        
        if destinos:
            # Seleciona unidade base (mais próxima do 1º ponto)
            u_base = min(unidades, key=lambda u: calcular_distancia_reta(u['lat'], u['lon'], destinos[0]['lat'], destinos[0]['lon']))
            
            coords = [[u_base['lon'], u_base['lat']]]
            labels = [u_base['nome']]
            for d in destinos:
                coords.append([d['lon'], d['lat']])
                labels.append(d['endereco'])
            coords.append([u_base['lon'], u_base['lat']])
            labels.append(f"Retorno {u_base['nome']}")

            res_api = ors_client.directions(coordinates=coords, profile='driving-car', format='geojson', optimize_waypoints=True)
            
            segs = res_api['features'][0]['properties']['segments']
            tabela = []
            for idx, s in enumerate(segs):
                tabela.append({
                    "Origem": labels[idx].replace(", São Bernardo do Campo", ""),
                    "Destino": labels[idx+1].replace(", São Bernardo do Campo", ""),
                    "Distância (km)": round(s['distance'] / 1000, 2),
                    "Tempo": f"{round(s['duration'] / 60, 1)} min"
                })

            st.session_state.resultado_rota = {
                "unidade": u_base,
                "paradas": destinos,
                "km_total": round(res_api['features'][0]['properties']['summary']['distance'] / 1000, 2),
                "tempo_total": round(res_api['features'][0]['properties']['summary']['duration'] / 60, 0),
                "geo": [[p[1], p[0]] for p in res_api['features'][0]['geometry']['coordinates']],
                "tabela": tabela
            }

# --- 6. EXIBIÇÃO DOS RESULTADOS ---
if st.session_state.resultado_rota:
    r = st.session_state.resultado_rota
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Base", r['unidade']['nome'])
    c2.metric("Total Distância", f"{r['km_total']} km")
    c3.metric("Tempo Total", f"{int(r['tempo_total'])} min")

    st.divider()
    col_t, col_m = st.columns([1.1, 1])

    with col_t:
        st.subheader("📋 Detalhamento de Trechos")
        st.dataframe(pd.DataFrame(r['tabela']), use_container_width=True, hide_index=True)
        
        # MARCA D'ÁGUA TECNOLAB3
        if img_b64:
            st.markdown(
                f"""
                <div style="text-align: center; margin-top: 40px; opacity: 0.12; filter: grayscale(100%);">
                    <img src="{img_b64}" width="300">
                </div>
                """, unsafe_allow_html=True
            )
        
        if st.button("🗑️ Nova Rota", use_container_width=True):
            st.session_state.resultado_rota = None
            st.rerun()

    with col_m:
        st.subheader("🗺️ Visualização do Mapa")
        m = folium.Map(location=[r['unidade']['lat'], r['unidade']['lon']], zoom_start=12)
        folium.Marker([r['unidade']['lat'], r['unidade']['lon']], icon=folium.Icon(color='green', icon='home')).add_to(m)
        for i, d in enumerate(r['paradas']):
            folium.Marker([d['lat'], d['lon']], icon=folium.Icon(color='blue'), tooltip=f"Parada {i+1}").add_to(m)
        folium.PolyLine(r['geo'], color="#2E86C1", weight=5, opacity=0.8).add_to(m)
        st_folium(m, use_container_width=True, height=550, key="mapa_final")
else:
    st.info("💡 Insira os CEPs na barra lateral para gerar o roteiro da frota Tecnolab.")
