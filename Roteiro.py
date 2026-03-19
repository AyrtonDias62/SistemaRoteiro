import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Roteirizador Tecnolab V9.2", layout="wide", page_icon="🚚")

# --- CSS ADAPTÁVEL ---
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    [data-testid="stMetric"] {
        background-color: var(--secondary-background-color);
        padding: 10px 15px;
        border-radius: 10px;
        border: 1px solid rgba(128, 128, 128, 0.2);
    }
    .titulo-roteiro { color: #2E86C1; margin: 0; font-size: 24px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. FUNÇÕES DE SUPORTE ---
def get_image_base64(path):
    try:
        with Image.open(path) as img:
            img = img.convert("RGBA")
            with io.BytesIO() as buffer:
                img.save(buffer, format="PNG")
                return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    except: return None

@st.cache_data(show_spinner=False)
def get_coords_cep(cep, _client_ors):
    try:
        r = requests.get(f"https://viacep.com.br/ws/{cep.replace('-','')}/json/").json()
        if "erro" in r: return None
        logra, cidade = r.get('logradouro', 'N/A'), r.get('localidade', 'N/A')
        geo = _client_ors.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
        if geo and len(geo['features']) > 0:
            c = geo['features'][0]['geometry']['coordinates']
            return {"lat": c[1], "lon": c[0], "endereco": f"{logra}, {r.get('bairro','')}"}
        return None
    except: return None

def selecionar_melhor_unidade(ponto_destino, lista_unidades, _client_ors):
    melhor_unid = lista_unidades[0]
    menor_distancia = float('inf')
    for u in lista_unidades:
        try:
            rota = _client_ors.directions(coordinates=[[u['lon'], u['lat']], [ponto_destino['lon'], ponto_destino['lat']]], profile='driving-car')
            dist = rota['features'][0]['properties']['summary']['distance']
            if dist < menor_distancia:
                menor_distancia = dist
                melhor_unid = u
        except: continue
    return melhor_unid

# --- 3. ASSETS E API ---
img_b64 = get_image_base64("furgao_tecnolab.png")

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

if "resultado_v9" not in st.session_state:
    st.session_state.resultado_v9 = None

# --- 4. CABEÇALHO ---
st.markdown(f"""<div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px; border-bottom: 2px solid #2E86C1; padding-bottom: 10px;">
    {f'<img src="{img_b64}" height="50">' if img_b64 else ''}
    <h1 class="titulo-roteiro">Roteirizador Tecnolab: Cliente x Unidade</h1>
</div>""", unsafe_allow_html=True)

# --- 5. SIDEBAR ---
with st.sidebar:
    st.header("📍 Itinerário")
    tipo_calc = st.radio("Modo de Roteirização:", ["Manter Ordem (Lista)", "Otimizar Caminho (IA)"])
    
    ceps_input = []
    for i in range(5):
        val = st.text_input(f"CEP Parada {i+1}:", key=f"cep_v92_{i}")
        if val: ceps_input.append(val)
    
    btn = st.button("🚀 Gerar Itinerário", use_container_width=True)

# --- 6. PROCESSAMENTO ---
if btn and ceps_input:
    with st.spinner("Calculando melhor logística..."):
        pontos_gps = []
        for c in ceps_input:
            p = get_coords_cep(c, ors_client)
            if p: pontos_gps.append(p)
        
        if pontos_gps:
            u_base = selecionar_melhor_unidade(pontos_gps[0], unidades, ors_client)
            
            coords = [[u_base['lon'], u_base['lat']]]
            labels = [u_base['nome']]
            for p in pontos_gps:
                coords.append([p['lon'], p['lat']])
                labels.append(p['endereco'])
            coords.append([u_base['lon'], u_base['lat']])
            labels.append(f"Retorno: {u_base['nome']}")

            try:
                otimizar = (tipo_calc == "Otimizar Caminho (IA)")
                res = ors_client.directions(
                    coordinates=coords, profile='driving-car', format='geojson', optimize_waypoints=otimizar
                )

                idx_ordem = [0]
                if otimizar and 'waypoint_order' in res['metadata']['query']:
                    ordem_ia = res['metadata']['query']['waypoint_order']
                    idx_ordem.extend([i + 1 for i in ordem_ia])
                else:
                    idx_ordem = list(range(len(coords) - 1))
                idx_ordem.append(len(coords) - 1)

                labels_final = [labels[i] for i in idx_ordem]
                segs = res['features'][0]['properties']['segments']
                rows = []
                for idx, s in enumerate(segs):
                    rows.append({
                        "De": labels_final[idx].split(',')[0],
                        "Para": labels_final[idx+1].split(',')[0],
                        "Distância": f"{round(s['distance']/1000, 2)} km",
                        "Tempo": f"{round(s['duration']/60, 1)} min"
                    })

                st.session_state.resultado_v9 = {
                    "unidade": u_base,
                    "km": round(res['features'][0]['properties']['summary']['distance']/1000, 2),
                    "min": int(res['features'][0]['properties']['summary']['duration']/60),
                    "geo": [[p[1], p[0]] for p in res['features'][0]['geometry']['coordinates']],
                    "tabela": rows,
                    "pontos": pontos_gps
                }
                st.balloons()

            except Exception as e:
                st.error(f"Erro na Rota: {e}")

# --- 7. DISPLAY ---
if st.session_state.resultado_v9:
    r = st.session_state.resultado_v9
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Base de Origem", r['unidade']['nome'])
    m2.metric("Distância Total", f"{r['km']} km")
    m3.metric("Tempo Total", f"{r['min']} min")

    c_tab, c_map = st.columns([1, 1.2])
    with c_tab:
        st.write("📋 **Trechos do Percurso**")
        df_rota = pd.DataFrame(r['tabela'])
        st.dataframe(df_rota, use_container_width=True, hide_index=True)
        
        # BOTÃO DE DOWNLOAD CSV
        csv = df_rota.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 Baixar Itinerário (CSV)", csv, f"itinerario_{datetime.now().strftime('%H%M')}.csv", "text/csv", use_container_width=True)
        
        if st.button("🗑️ Nova Rota", use_container_width=True):
            st.session_state.resultado_v9 = None
            st.rerun()

    with c_map:
        m = folium.Map(location=[r['unidade']['lat'], r['unidade']['lon']], zoom_start=12)
        folium.Marker([r['unidade']['lat'], r['unidade']['lon']], icon=folium.Icon(color='green', icon='home')).add_to(m)
        for p in r['pontos']:
            folium.Marker([p['lat'], p['lon']], icon=folium.Icon(color='blue')).add_to(m)
        folium.PolyLine(r['geo'], color="#2E86C1", weight=6).add_to(m)
        st_folium(m, use_container_width=True, height=500, key="mapa_v92")
