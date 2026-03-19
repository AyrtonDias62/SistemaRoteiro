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

# --- 1. CONFIGURAÇÃO DA PÁGINA (Layout mais largo para o mapa) ---
st.set_page_config(page_title="Tecnolab Roteirizador V10.1", layout="wide", page_icon="🚚")

# Redução da largura da Sidebar para os CEPs não ocuparem espaço demais
st.markdown("""
    <style>
    [data-testid="stSidebar"][aria-expanded="true"]{
        min-width: 250px;
        max-width: 300px;
    }
    .block-container { padding-top: 1.5rem; }
    .stMetric { background-color: #f0f2f6; padding: 10px; border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

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
            return {"lat": c[1], "lon": c[0], "endereco": logra, "bairro": bairro, "cep": cep}
    except: return None

# --- 3. SETUP DE DADOS ---
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

if "res_v101" not in st.session_state: st.session_state.res_v101 = None

# --- 4. INTERFACE ---
st.markdown(f"""<div style="display: flex; align-items: center; gap: 15px; margin-bottom: 15px;">
    {f'<img src="{img_b64}" height="45">' if img_b64 else ''}
    <h2 style="color: #2E86C1; margin:0;">Roteirizador Tecnolab</h2>
</div>""", unsafe_allow_html=True)

with st.sidebar:
    st.subheader("📍 Entrada de Dados")
    tipo_calc = st.radio("Estratégia de Rota:", ["Manter Ordem", "Otimizar Caminho"], help="Otimizar reorganiza os CEPs para a rota mais curta.")
    
    ceps_input = []
    for i in range(5):
        val = st.text_input(f"CEP {i+1}:", key=f"cep101_{i}")
        if val: ceps_input.append(val)
    
    btn = st.button("🚀 Gerar Itinerário", use_container_width=True)

# --- 5. LÓGICA DE PROCESSAMENTO ---
if btn and ceps_input:
    with st.spinner("Calculando logística..."):
        pontos_gps = [get_coords_cep(c, ors_client) for c in ceps_input if get_coords_cep(c, ors_client)]
        
        if pontos_gps:
            u_base = unidades[0]
            # Coordenadas: [Base, P1, P2... P5, Base]
            coords_in = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pontos_gps] + [[u_base['lon'], u_base['lat']]]
            
            try:
                otimizar = (tipo_calc == "Otimizar Caminho")
                res = ors_client.directions(coordinates=coords_in, profile='driving-car', format='geojson', optimize_waypoints=otimizar)
                
                # REORDENAÇÃO REAL DOS PONTOS
                if otimizar and 'waypoint_order' in res['metadata']['query']:
                    # waypoint_order dá a ordem dos pontos intermediários. Ex: [1, 0]
                    ordem_idx = [0] + [i + 1 for i in res['metadata']['query']['waypoint_order']] + [len(coords_in)-1]
                else:
                    ordem_idx = list(range(len(coords_in)))

                # Nomes formatados na ordem correta
                labels_raw = [f"INÍCIO: {u_base['nome']}"] + [f"{p['endereco']} ({p['cep']})" for p in pontos_gps] + [f"RETORNO: {u_base['nome']}"]
                labels_finais = [labels_raw[i] for i in ordem_idx]
                
                tabela = []
                segs = res['features'][0]['properties']['segments']
                for i, s in enumerate(segs):
                    tabela.append({
                        "Parada": f"{i+1}º",
                        "Origem / Destino": f"{labels_finais[i+1]}",
                        "KM": f"{round(s['distance']/1000, 2)} km",
                        "Tempo": f"{round(s['duration']/60, 1)} min"
                    })

                # Marcadores para o mapa
                marcas = [{"lat": u_base['lat'], "lon": u_base['lon'], "pop": "1. INÍCIO", "cor": "green"}]
                if otimizar:
                    for i, o_idx in enumerate(res['metadata']['query']['waypoint_order']):
                        p = pontos_gps[o_idx]
                        marcas.append({"lat": p['lat'], "lon": p['lon'], "pop": f"{i+2}. {p['endereco']} ({p['cep']})", "cor": "blue"})
                else:
                    for i, p in enumerate(pontos_gps):
                        marcas.append({"lat": p['lat'], "lon": p['lon'], "pop": f"{i+2}. {p['endereco']} ({p['cep']})", "cor": "blue"})

                st.session_state.res_v101 = {
                    "tabela": tabela, 
                    "geo": [[p[1], p[0]] for p in res['features'][0]['geometry']['coordinates']], 
                    "marcas": marcas,
                    "centro": [u_base['lat'], u_base['lon']]
                }
            except Exception as e: st.error(f"Erro na rota: {e}")

# --- 6. EXIBIÇÃO ---
if st.session_state.res_v101:
    r = st.session_state.res_v101
    
    # Grid Principal: Tabela menor à esquerda, Mapa grande à direita
    col_tab, col_map = st.columns([0.8, 1.2])
    
    with col_tab:
        st.write("📋 **Itinerário Passo a Passo**")
        st.dataframe(pd.DataFrame(r['tabela']), use_container_width=True, hide_index=True)
        
        csv = pd.DataFrame(r['tabela']).to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 Baixar CSV", csv, "itinerario.csv", "text/csv", use_container_width=True)
        
        if st.button("🗑️ Nova Rota", use_container_width=True):
            st.session_state.res_v101 = None
            st.rerun()

    with col_map:
        m = folium.Map(location=r['centro'], zoom_start=12, tiles="cartodbpositron")
        for p in r['marcas']:
            folium.Marker([p['lat'], p['lon']], icon=folium.Icon(color=p['cor']), tooltip=p['pop']).add_to(m)
        folium.PolyLine(r['geo'], color="#2E86C1", weight=5, opacity=0.8).add_to(m)
        st_folium(m, use_container_width=True, height=600, key="map101")
