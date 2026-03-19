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

# --- 1. CONFIGURAÇÃO E CSS ---
st.set_page_config(page_title="Tecnolab Roteirizador V10.3", layout="wide", page_icon="🚚")

st.markdown("""
    <style>
    /* CSS para forçar a sidebar a ser estreita */
    [data-testid="stSidebar"] {
        min-width: 200px !important;
        max-width: 250px !important;
    }
    .block-container { padding-top: 1rem; }
    .stMetric { background-color: #f8f9fa; padding: 10px; border-radius: 8px; border: 1px solid #dee2e6; }
    .titulo-pg { color: #2E86C1; font-size: 20px; font-weight: bold; margin-bottom: 0; }
    /* Ajuste de padding dos inputs na sidebar */
    div[data-testid="stTextInput"] { margin-bottom: -15px; }
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
        logra, bairro = r.get('logradouro', 'N/A'), r.get('bairro', 'N/A')
        geo = _client_ors.pelias_search(text=f"{logra}, {bairro}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
        if geo and len(geo['features']) > 0:
            c = geo['features'][0]['geometry']['coordinates']
            return {"lat": c[1], "lon": c[0], "endereco": logra, "cep": cep}
    except: return None

# --- 3. DADOS FIXOS ---
img_b64 = get_image_base64("furgao_tecnolab.png")
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro na chave da API."); st.stop()

u_base = {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594}

if "res_v103" not in st.session_state: st.session_state.res_v103 = None

# --- 4. CABEÇALHO ---
st.markdown(f"""<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 5px;">
    {f'<img src="{img_b64}" height="35">' if img_b64 else ''}
    <p class="titulo-pg">Roteirizador Tecnolab</p>
</div>""", unsafe_allow_html=True)

# --- 5. SIDEBAR ---
with st.sidebar:
    st.write("⚙️ **Modo de Rota**")
    tipo_calc = st.radio("Estratégia:", ["Ordem da Lista", "Melhor Caminho (IA)"], label_visibility="collapsed")
    
    st.divider()
    st.write("📍 **Destinos**")
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"C{i}", key=f"c103_{i}", label_visibility="collapsed", placeholder=f"CEP {i+1}")
        if c: ceps_raw.append(c)
    
    btn = st.button("🚀 CALCULAR", use_container_width=True)

# --- 6. PROCESSAMENTO ---
if btn and ceps_raw:
    with st.spinner("Processando..."):
        pontos = [get_coords_cep(c, ors_client) for c in ceps_raw if get_coords_cep(c, ors_client)]
        
        if pontos:
            # Lista de coordenadas [Início, P1, P2..., Fim]
            coords_origem = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pontos] + [[u_base['lon'], u_base['lat']]]
            labels_origem = [f"INÍCIO: {u_base['nome']}"] + [f"{p['endereco']} ({p['cep']})" for p in pontos] + [f"RETORNO: {u_base['nome']}"]
            
            try:
                # SOLUÇÃO PARA OTIMIZAÇÃO REAL:
                if tipo_calc == "Melhor Caminho (IA)":
                    # Chamada explícita de otimização
                    res = ors_client.directions(coordinates=coords_origem, profile='driving-car', format='geojson', optimize_waypoints=True)
                    # A API retorna a ordem dos pontos intermediários no waypoint_order
                    # Ex: se digitou CEP_A, CEP_B e a melhor rota é B depois A, ela retorna [1, 0]
                    ordem_indices = [0] + [i + 1 for i in res['metadata']['query']['waypoint_order']] + [len(coords_origem)-1]
                else:
                    # Ordem exata da lista digitada
                    res = ors_client.directions(coordinates=coords_origem, profile='driving-car', format='geojson', optimize_waypoints=False)
                    ordem_indices = list(range(len(coords_origem)))

                # Montagem da Tabela e do Mapa baseada nos índices finais
                labels_ordenadas = [labels_origem[i] for i in ordem_indices]
                
                tabela_final = []
                # Linha 0: Local de Saída
                tabela_final.append({"Seq": "0", "Localização": labels_ordenadas[0], "Distância": "-", "Tempo": "-"})
                
                segmentos = res['features'][0]['properties']['segments']
                for i, s in enumerate(segmentos):
                    tabela_final.append({
                        "Seq": f"{i+1}º",
                        "Localização": labels_ordenadas[i+1],
                        "Distância": f"{round(s['distance']/1000, 2)} km",
                        "Tempo": f"{round(s['duration']/60, 1)} min"
                    })

                # Marcadores para o Mapa seguindo a ordem visual
                marcas_mapa = [{"lat": u_base['lat'], "lon": u_base['lon'], "txt": "0. SAÍDA", "cor": "green"}]
                # Se for otimizado, precisamos remapear os pontos GPS para a ordem da IA
                if tipo_calc == "Melhor Caminho (IA)":
                    for seq, idx_orig in enumerate(res['metadata']['query']['waypoint_order']):
                        p = pontos[idx_orig]
                        marcas_mapa.append({"lat": p['lat'], "lon": p['lon'], "txt": f"{seq+1}. {p['endereco']}", "cor": "blue"})
                else:
                    for seq, p in enumerate(pontos):
                        marcas_mapa.append({"lat": p['lat'], "lon": p['lon'], "txt": f"{seq+1}. {p['endereco']}", "cor": "blue"})

                st.session_state.res_v103 = {
                    "tabela": tabela_final, 
                    "geo": [[p[1], p[0]] for p in res['features'][0]['geometry']['coordinates']], 
                    "marcas": marcas_mapa,
                    "centro": [u_base['lat'], u_base['lon']]
                }
            except Exception as e: st.error(f"Erro no cálculo: {e}")

# --- 7. EXIBIÇÃO ---
if st.session_state.res_v103:
    r = st.session_state.res_v103
    col_tab, col_map = st.columns([0.8, 1.2])
    
    with col_tab:
        st.write("📋 **Itinerário Ordenado**")
        st.dataframe(pd.DataFrame(r['tabela']), use_container_width=True, hide_index=True)
        if st.button("🗑️ Limpar", use_container_width=True):
            st.session_state.res_v103 = None
            st.rerun()

    with col_map:
        m = folium.Map(location=r['centro'], zoom_start=12, tiles="cartodbpositron")
        for p in r['marcas']:
            folium.Marker([p['lat'], p['lon']], icon=folium.Icon(color=p['cor']), tooltip=p['txt']).add_to(m)
        folium.PolyLine(r['geo'], color="#2E86C1", weight=6).add_to(m)
        st_folium(m, use_container_width=True, height=650, key="map103")
