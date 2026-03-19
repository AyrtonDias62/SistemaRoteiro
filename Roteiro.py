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
st.set_page_config(page_title="Roteirizador Tecnolab V9.9", layout="wide", page_icon="🚚")

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

if "res_v99" not in st.session_state: st.session_state.res_v99 = None

# --- 4. UI ---
st.markdown(f"""<div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px; border-bottom: 2px solid #2E86C1; padding-bottom: 10px;">
    {f'<img src="{img_b64}" height="50">' if img_b64 else ''}
    <h1 style="color: #2E86C1; margin:0; font-size: 24px;">Roteirizador Tecnolab V9.9</h1>
</div>""", unsafe_allow_html=True)

with st.sidebar:
    st.header("📍 Configuração")
    tipo_calc = st.selectbox("Estratégia de Rota:", ["Manter Ordem (Lista)", "Otimizar Caminho (IA)"])
    ceps_in = [st.text_input(f"Parada {i+1}:", key=f"c99_{i}") for i in range(5)]
    ceps_validos = [c for c in ceps_in if c.strip()]
    btn = st.button("🚀 Calcular Rota", use_container_width=True)

# --- 5. LÓGICA DE ROTA ---
if btn and ceps_validos:
    with st.spinner("Otimizando trajeto..."):
        pontos_originais = []
        for c in ceps_validos:
            p = get_coords_cep(c, ors_client)
            if p: pontos_originais.append(p)
        
        if pontos_originais:
            u_base = selecionar_melhor_unidade(pontos_originais[0], unidades, ors_client)
            # Coordenadas: [Base, P1, P2, P3, P4, P5, Base]
            coords_input = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pontos_originais] + [[u_base['lon'], u_base['lat']]]
            
            geo_final = []
            tabela = []
            pontos_ordenados_mapa = []

            # --- MODO 1: LISTA DIRETA ---
            if tipo_calc == "Manter Ordem (Lista)":
                labels_lista = [u_base['nome']] + [f"{p['endereco']} ({p['cep']})" for p in pontos_originais] + [f"Fim: {u_base['nome']}"]
                for i in range(len(coords_input) - 1):
                    res = ors_client.directions(coordinates=[coords_input[i], coords_input[i+1]], profile='driving-car', format='geojson')
                    s = res['features'][0]['properties']['summary']
                    geo_final.extend([[p[1], p[0]] for p in res['features'][0]['geometry']['coordinates']])
                    tabela.append({
                        "Ordem": f"{i+1}º", "De": labels_lista[i], "Para": labels_lista[i+1],
                        "Distância": f"{round(s['distance']/1000, 2)} km", "Tempo": f"{round(s['duration']/60, 1)} min"
                    })
                # Para o mapa
                pontos_ordenados_mapa = [{"lat": u_base['lat'], "lon": u_base['lon'], "label": f"1. Início: {u_base['nome']}", "tipo": "base"}]
                for i, p in enumerate(pontos_originais):
                    pontos_ordenados_mapa.append({"lat": p['lat'], "lon": p['lon'], "label": f"{i+2}. {p['endereco']} ({p['cep']})", "tipo": "cliente"})

            # --- MODO 2: OTIMIZAÇÃO IA ---
            else:
                res = ors_client.directions(coordinates=coords_input, profile='driving-car', format='geojson', optimize_waypoints=True)
                # waypoint_order nos diz a ordem dos pontos intermediários (ex: [2, 0, 1] significa que o 3º CEP do input é o primeiro a ser visitado)
                ordem_ia = res['metadata']['query']['waypoint_order']
                # Reconstruindo a sequência de índices: [Base (0), ...IA..., Retorno (Final)]
                idx_sequencia = [0] + [i + 1 for i in ordem_ia] + [len(coords_input)-1]
                
                # Labels originais para busca por índice
                labels_raw = [u_base['nome']] + [f"{p['endereco']} ({p['cep']})" for p in pontos_originais] + [f"Fim: {u_base['nome']}"]
                labels_finais = [labels_raw[i] for i in idx_sequencia]
                
                geo_final = [[p[1], p[0]] for p in res['features'][0]['geometry']['coordinates']]
                segmentos = res['features'][0]['properties']['segments']
                
                for i, s in enumerate(segmentos):
                    tabela.append({
                        "Ordem": f"{i+1}º", "De": labels_finais[i], "Para": labels_finais[i+1],
                        "Distância": f"{round(s['distance']/1000, 2)} km", "Tempo": f"{round(s['duration']/60, 1)} min"
                    })
                
                # Para o mapa (pontos com numeração correta da IA)
                pontos_ordenados_mapa = [{"lat": u_base['lat'], "lon": u_base['lon'], "label": "1. Início / Fim", "tipo": "base"}]
                for i, pos_original in enumerate(ordem_ia):
                    p = pontos_originais[pos_original]
                    pontos_ordenados_mapa.append({"lat": p['lat'], "lon": p['lon'], "label": f"{i+2}. {p['endereco']} ({p['cep']})", "tipo": "cliente"})

            st.session_state.res_v99 = {
                "unidade": u_base, "tabela": tabela, "geo": geo_final, "pontos": pontos_ordenados_mapa, "modo": tipo_calc
            }

# --- 6. DISPLAY ---
if st.session_state.res_v99:
    r = st.session_state.res_v99
    col_t, col_m = st.columns([1.2, 1])
    
    with col_t:
        st.subheader(f"📋 Itinerário: {r['modo']}")
        st.dataframe(pd.DataFrame(r['tabela']), use_container_width=True, hide_index=True)
        if st.button("🗑️ Nova Rota"): 
            st.session_state.res_v99 = None
            st.rerun()

    with col_m:
        st.subheader("🗺️ Ordem das Paradas")
        m = folium.Map(location=[r['unidade']['lat'], r['unidade']['lon']], zoom_start=12)
        for p in r['pontos']:
            cor = 'green' if p['tipo'] == 'base' else 'blue'
            folium.Marker([p['lat'], p['lon']], icon=folium.Icon(color=cor), tooltip=p['label']).add_to(m)
        folium.PolyLine(r['geo'], color="#2E86C1", weight=6).add_to(m)
        st_folium(m, use_container_width=True, height=500, key="map99")
