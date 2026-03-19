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

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V10.0", layout="wide", page_icon="🚚")

# --- 2. FUNÇÕES ---
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
        clean_cep = str(cep).replace('-','').replace(' ', '').strip()
        r = requests.get(f"https://viacep.com.br/ws/{clean_cep}/json/").json()
        if "erro" in r: return None
        logra, bairro, cidade = r.get('logradouro', 'N/A'), r.get('bairro', 'N/A'), r.get('localidade', 'N/A')
        geo = _client_ors.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
        if geo and len(geo['features']) > 0:
            c = geo['features'][0]['geometry']['coordinates']
            return {"lat": c[1], "lon": c[0], "endereco": f"{logra}, {bairro}", "cep": cep}
    except: return None

# --- 3. SETUP ---
img_b64 = get_image_base64("furgao_tecnolab.png")
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro na ORS_KEY."); st.stop()

unidades = [
    {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594},
    {"nome": "Tecno U2", "lat": -23.70601, "lon": -46.54946},
    {"nome": "Tecno U4", "lat": -23.709069, "lon": -46.413002},
    {"nome": "Tecno U5", "lat": -23.65458, "lon": -46.53554},
    {"nome": "Tecno U13", "lat": -23.68791, "lon": -46.62192},
]

if "res_v10" not in st.session_state: st.session_state.res_v10 = None

# --- 4. UI ---
st.markdown(f"""<div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px; border-bottom: 2px solid #2E86C1; padding-bottom: 10px;">
    {f'<img src="{img_b64}" height="50">' if img_b64 else ''}
    <h1 style="color: #2E86C1; margin:0; font-size: 24px;">Roteirizador Tecnolab V10.0</h1>
</div>""", unsafe_allow_html=True)

with st.sidebar:
    st.header("📍 Painel de Controle")
    tipo_calc = st.radio("Estratégia:", ["Manter Ordem (Lista Direta)", "Otimizar Rota (Melhor Caminho)"])
    ceps_in = [st.text_input(f"CEP Parada {i+1}:", key=f"c10_{i}") for i in range(5)]
    ceps_validos = [c for c in ceps_in if c.strip()]
    btn = st.button("🚀 Gerar Roteiro", use_container_width=True)

# --- 5. LÓGICA CORE ---
if btn and ceps_validos:
    with st.spinner("Analisando logradouros..."):
        pontos_gps = [get_coords_cep(c, ors_client) for c in ceps_validos if get_coords_cep(c, ors_client)]
        
        if pontos_gps:
            # Seleção da base (sempre fixa como início e fim)
            u_base = unidades[0] # Ou use sua função selecionar_melhor_unidade
            coords_input = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pontos_gps] + [[u_base['lon'], u_base['lat']]]
            
            try:
                otimizar = (tipo_calc == "Otimizar Rota (Melhor Caminho)")
                res = ors_client.directions(coordinates=coords_input, profile='driving-car', format='geojson', optimize_waypoints=otimizar)
                
                # RECONSTRUÇÃO DA ORDEM DOS PONTOS
                if otimizar and 'waypoint_order' in res['metadata']['query']:
                    ordem_indices = [0] + [i + 1 for i in res['metadata']['query']['waypoint_order']] + [len(coords_input)-1]
                else:
                    ordem_indices = list(range(len(coords_input)))

                # Montagem das Labels e Tabela com base na ordem REAL decidida
                labels_raw = [u_base['nome']] + [f"{p['endereco']} ({p['cep']})" for p in pontos_gps] + [f"Fim: {u_base['nome']}"]
                labels_finais = [labels_raw[i] for i in ordem_indices]
                
                tabela = []
                segs = res['features'][0]['properties']['segments']
                for i, s in enumerate(segs):
                    tabela.append({
                        "Passo": f"{i+1}º",
                        "Origem": labels_finais[i],
                        "Destino": labels_finais[i+1],
                        "KM": f"{round(s['distance']/1000, 2)} km",
                        "Tempo": f"{round(s['duration']/60, 1)} min"
                    })

                # Preparação dos Marcadores para o Mapa com numeração
                mapa_pontos = []
                # Início
                mapa_pontos.append({"lat": u_base['lat'], "lon": u_base['lon'], "txt": f"1. INÍCIO: {u_base['nome']}", "cor": "green"})
                # Intermediários na ordem correta
                if otimizar:
                    for i, pos_orig in enumerate(res['metadata']['query']['waypoint_order']):
                        p = pontos_gps[pos_orig]
                        mapa_pontos.append({"lat": p['lat'], "lon": p['lon'], "txt": f"{i+2}. {p['endereco']} | CEP: {p['cep']}", "cor": "blue"})
                else:
                    for i, p in enumerate(pontos_gps):
                        mapa_pontos.append({"lat": p['lat'], "lon": p['lon'], "txt": f"{i+2}. {p['endereco']} | CEP: {p['cep']}", "cor": "blue"})

                st.session_state.res_v10 = {
                    "tabela": tabela, 
                    "geo": [[p[1], p[0]] for p in res['features'][0]['geometry']['coordinates']], 
                    "pontos": mapa_pontos,
                    "centro": [u_base['lat'], u_base['lon']]
                }
            except Exception as e: st.error(f"Erro na API: {e}")

# --- 6. DISPLAY ---
if st.session_state.res_v10:
    r = st.session_state.res_v10
    col1, col2 = st.columns([1.2, 1])
    
    with col1:
        st.subheader("📋 Itinerário Ordenado")
        st.dataframe(pd.DataFrame(r['tabela']), use_container_width=True, hide_index=True)
        if st.button("🗑️ Nova Rota"): st.session_state.res_v10 = None; st.rerun()

    with col2:
        st.subheader("🗺️ Visualização da Ordem")
        m = folium.Map(location=r['centro'], zoom_start=12)
        for p in r['pontos']:
            folium.Marker([p['lat'], p['lon']], icon=folium.Icon(color=p['cor']), tooltip=p['txt']).add_to(m)
        folium.PolyLine(r['geo'], color="#2E86C1", weight=6).add_to(m)
        st_folium(m, use_container_width=True, height=500, key="map10")
