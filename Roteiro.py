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

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V9.6", layout="wide", page_icon="🚚")

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; }
    [data-testid="stMetric"] { background-color: var(--secondary-background-color); padding: 10px; border-radius: 10px; border: 1px solid rgba(128,128,128,0.2); }
    .titulo-roteiro { color: #2E86C1; font-weight: bold; font-size: 24px; }
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
        if not clean_cep: return None
        r = requests.get(f"https://viacep.com.br/ws/{clean_cep}/json/").json()
        if "erro" in r: return None
        logra, bairro, cidade = r.get('logradouro', 'N/A'), r.get('bairro', 'N/A'), r.get('localidade', 'N/A')
        geo = _client_ors.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
        if geo and len(geo['features']) > 0:
            c = geo['features'][0]['geometry']['coordinates']
            return {"lat": c[1], "lon": c[0], "endereco": f"{logra}, {bairro}", "cep": cep}
    except: return None

def selecionar_melhor_unidade(ponto_destino, lista_unidades, _client_ors):
    melhor_unid, menor_dist = lista_unidades[0], float('inf')
    for u in lista_unidades:
        try:
            rota = _client_ors.directions(coordinates=[[u['lon'], u['lat']], [ponto_destino['lon'], ponto_destino['lat']]], profile='driving-car')
            dist = rota['features'][0]['properties']['summary']['distance']
            if dist < menor_dist: menor_dist = dist; melhor_unid = u
        except: continue
    return melhor_unid

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

if "res_v96" not in st.session_state: st.session_state.res_v96 = None

# --- 4. INTERFACE ---
st.markdown(f"""<div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px; border-bottom: 2px solid #2E86C1; padding-bottom: 10px;">
    {f'<img src="{img_b64}" height="50">' if img_b64 else ''}
    <h1 class="titulo-roteiro">Roteirizador Tecnolab: Gestão de Itinerário</h1>
</div>""", unsafe_allow_html=True)

with st.sidebar:
    st.header("📍 Itinerário")
    tipo_calc = st.radio("Estratégia:", ["Manter Ordem (Lista)", "Otimizar Caminho (Melhor Ordem)"])
    ceps_in = [st.text_input(f"Parada {i+1}:", key=f"c96_{i}") for i in range(5)]
    ceps_validos = [c for c in ceps_in if c.strip()]
    btn = st.button("🚀 Gerar Rota", use_container_width=True)

# --- 5. LÓGICA ---
if btn and ceps_validos:
    with st.spinner("Mapeando pontos..."):
        pontos = []
        for c in ceps_validos:
            p = get_coords_cep(c, ors_client)
            if p: 
                pontos.append(p)
            else:
                st.warning(f"CEP {c} não localizado e será ignorado.")
        
        if pontos:
            u_base = selecionar_melhor_unidade(pontos[0], unidades, ors_client)
            # Coordenadas: Base -> Pontos -> Base
            coords = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pontos] + [[u_base['lon'], u_base['lat']]]
            labels_original = [u_base['nome']] + [f"{p['endereco']} (CEP: {p['cep']})" for p in pontos] + [f"Retorno: {u_base['nome']}"]

            otimizar = (tipo_calc == "Otimizar Caminho (Melhor Ordem)")
            
            try:
                res = ors_client.directions(coordinates=coords, profile='driving-car', format='geojson', optimize_waypoints=otimizar)
                
                # Reconstrução da ordem
                if otimizar and 'waypoint_order' in res['metadata']['query']:
                    ordem_ia = res['metadata']['query']['waypoint_order']
                    idx_final = [0] + [i + 1 for i in ordem_ia] + [len(coords)-1]
                else:
                    idx_final = list(range(len(coords)))

                labels_ordenadas = [labels_original[i] for i in idx_final]
                segs = res['features'][0]['properties']['segments']
                tabela = []
                for idx, s in enumerate(segs):
                    tabela.append({
                        "De": labels_ordenadas[idx],
                        "Para": labels_ordenadas[idx+1],
                        "Distância": f"{round(s['distance']/1000, 2)} km",
                        "Tempo": f"{round(s['duration']/60, 1)} min"
                    })

                st.session_state.res_v96 = {
                    "unidade": u_base, "km": round(res['features'][0]['properties']['summary']['distance']/1000, 2),
                    "min": int(res['features'][0]['properties']['summary']['duration']/60),
                    "geo": [[p[1], p[0]] for p in res['features'][0]['geometry']['coordinates']],
                    "tabela": tabela, "pontos_mapa": pontos, "modo": tipo_calc
                }
                st.toast("Rota gerada com sucesso!")
            except Exception as e: st.error(f"Erro na API: {e}")

# --- 6. EXIBIÇÃO ---
if st.session_state.res_v96:
    r = st.session_state.res_v96
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Base", r['unidade']['nome']); m2.metric("Distância", f"{r['km']} km"); m3.metric("Tempo Est.", f"{r['min']} min")

    c1, c2 = st.columns([1, 1.2])
    with c1:
        st.write(f"Estratégia: **{r['modo']}**")
        st.dataframe(pd.DataFrame(r['tabela']), use_container_width=True, hide_index=True)
        csv = pd.DataFrame(r['tabela']).to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 Exportar Itinerário", csv, "itinerario.csv", "text/csv", use_container_width=True)
        if st.button("🗑️ Nova Rota", use_container_width=True): 
            st.session_state.res_v96 = None
            st.rerun()
    
    with c2:
        m = folium.Map(location=[r['unidade']['lat'], r['unidade']['lon']], zoom_start=12)
        
        # Marcador Unidade
        folium.Marker(
            [r['unidade']['lat'], r['unidade']['lon']], 
            icon=folium.Icon(color='green', icon='home'), 
            tooltip=f"<b>BASE:</b> {r['unidade']['nome']}"
        ).add_to(m)
        
        # Marcadores Clientes (Tooltip Unificado)
        for p in r['pontos_mapa']:
            folium.Marker(
                [p['lat'], p['lon']], 
                icon=folium.Icon(color='blue', icon='user'), 
                tooltip=f"<b>Endereço:</b> {p['endereco']}<br><b>CEP:</b> {p['cep']}"
            ).add_to(m)

        folium.PolyLine(r['geo'], color="#2E86C1", weight=6, opacity=0.8).add_to(m)
        st_folium(m, use_container_width=True, height=500, key="map96")
