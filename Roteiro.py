import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
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

# --- CSS REVISADO (EQUILÍBRIO DE ESPAÇO) ---
st.markdown("""
    <style>
    .block-container {
        padding-top: 2rem; 
        padding-bottom: 0rem;
    }
    [data-testid="stMetric"] {
        background-color: #f0f2f6;
        padding: 5px 15px;
        border-radius: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. FUNÇÕES DE SUPORTE ---
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
    try:
        r = requests.get(f"https://viacep.com.br/ws/{cep.replace('-','')}/json/").json()
        if "erro" in r: return None
        logra, bairro, cidade = r.get('logradouro', 'N/A'), r.get('bairro', 'N/A'), r.get('localidade', 'N/A')
        geo = client_ors.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
        if geo and len(geo['features']) > 0:
            c = geo['features'][0]['geometry']['coordinates']
            return {"lat": c[1], "lon": c[0], "endereco": f"{logra}, {bairro}"}
        return None
    except:
        return None

# --- 3. ASSETS E API ---
img_b64 = get_image_base64("furgao_tecnolab3.png")

try:
    api_key = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=api_key)
except:
    st.error("Erro: Verifique a ORS_KEY nas Secrets.")
    st.stop()

unidades = [
    {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594},
    {"nome": "Tecno U2", "lat": -23.70601, "lon": -46.54946},
    {"nome": "Tecno U4", "lat": -23.709069, "lon": -46.413002},
    {"nome": "Tecno U5", "lat": -23.65458, "lon": -46.53554},
    {"nome": "Tecno U13", "lat": -23.68791, "lon": -46.62192},
]

if "resultado_rota" not in st.session_state:
    st.session_state.resultado_rota = None

# --- 4. TÍTULO ---
if img_b64:
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 15px;">
            <img src="{img_b64}" height="45">
            <h2 style="color: #2E86C1; margin: 0;">Roteirizador Tecnolab</h2>
        </div>
        """, unsafe_allow_html=True
    )
else:
    st.title("Roteirizador Tecnolab")

# --- 5. BARRA LATERAL (CEPs INDEPENDENTES) ---
with st.sidebar:
    st.header("📍 Itinerário")
    ceps_finais = []
    for i in range(5):
        # Cada campo tem sua chave única 'cep_slot_X' para evitar replicação
        entrada = st.text_input(f"CEP Parada {i+1}:", value="", key=f"cep_slot_{i}")
        if entrada:
            ceps_finais.append(entrada)
    
    btn_calc = st.button("Gerar Rota Otimizada", use_container_width=True)

if btn_calc and ceps_finais:
    with st.spinner("Calculando percurso..."):
        destinos = []
        for cp in ceps_finais:
            info = get_coords_cep(cp, ors_client)
            if info: destinos.append(info)
        
        if destinos:
            u_base = min(unidades, key=lambda u: calcular_distancia_reta(u['lat'], u['lon'], destinos[0]['lat'], destinos[0]['lon']))
            coords = [[u_base['lon'], u_base['lat']]]
            labels = [u_base['nome']]
            for d in destinos:
                coords.append([d['lon'], d['lat']])
                labels.append(d['endereco'])
            coords.append([u_base['lon'], u_base['lat']])
            labels.append(f"Fim: {u_base['nome']}")

            res_api = ors_client.directions(coordinates=coords, profile='driving-car', format='geojson', optimize_waypoints=True)
            
            segs = res_api['features'][0]['properties']['segments']
            tabela_data = []
            for idx, s in enumerate(segs):
                tabela_data.append({
                    "Origem": labels[idx].replace(", São Bernardo do Campo", "").replace(", SP", ""),
                    "Destino": labels[idx+1].replace(", São Bernardo do Campo", "").replace(", SP", ""),
                    "KM": round(s['distance'] / 1000, 2),
                    "Tempo": f"{round(s['duration'] / 60, 1)} min"
                })

            st.session_state.resultado_rota = {
                "unidade": u_base, "paradas": destinos,
                "km_total": round(res_api['features'][0]['properties']['summary']['distance'] / 1000, 2),
                "tempo_total": round(res_api['features'][0]['properties']['summary']['duration'] / 60, 0),
                "geo": [[p[1], p[0]] for p in res_api['features'][0]['geometry']['coordinates']],
                "tabela": tabela_data
            }

# --- 6. EXIBIÇÃO ---
if st.session_state.resultado_rota:
    r = st.session_state.resultado_rota
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Unidade Base", r['unidade']['nome'])
    c2.metric("Distância Total", f"{r['km_total']} km")
    c3.metric("Tempo Previsto", f"{int(r['tempo_total'])} min")

    st.write("") 

    col_t, col_m = st.columns([1, 1.2])

    with col_t:
        st.markdown("##### 📋 Trechos Detalhados")
        st.dataframe(pd.DataFrame(r['tabela']), use_container_width=True, hide_index=True, height=300)
        
        if st.button("🗑️ Nova Rota", use_container_width=True):
            # Limpa especificamente as chaves de entrada para zerar o formulário
            for key in st.session_state.keys():
                if "cep_slot_" in key:
                    st.session_state[key] = ""
            st.session_state.resultado_rota = None
            st.rerun()

    with col_m:
        st.markdown("##### 🗺️ Mapa da Frota")
        m = folium.Map(location=[r['unidade']['lat'], r['unidade']['lon']], zoom_start=12)
        folium.Marker([r['unidade']['lat'], r['unidade']['lon']], icon=folium.Icon(color='green', icon='home')).add_to(m)
        for i, d in enumerate(r['paradas']):
            folium.Marker([d['lat'], d['lon']], icon=folium.Icon(color='blue'), tooltip=f"Ponto {i+1}").add_to(m)
        folium.PolyLine(r['geo'], color="#2E86C1", weight=6, opacity=0.8).add_to(m)
        st_folium(m, use_container_width=True, height=500, key="mapa_final_v79")
else:
    st.info("Insira os CEPs individualmente na barra lateral para gerar o roteiro Tecnolab.")
