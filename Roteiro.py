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
st.set_page_config(page_title="Roteirizador Tecnolab V9.8", layout="wide", page_icon="🚚")

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
    st.error("Erro: ORS_KEY não configurada."); st.stop()

unidades = [
    {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594},
    {"nome": "Tecno U2", "lat": -23.70601, "lon": -46.54946},
    {"nome": "Tecno U4", "lat": -23.709069, "lon": -46.413002},
    {"nome": "Tecno U5", "lat": -23.65458, "lon": -46.53554},
    {"nome": "Tecno U13", "lat": -23.68791, "lon": -46.62192},
]

if "res_v98" not in st.session_state: st.session_state.res_v98 = None

# --- 4. UI ---
st.markdown(f"""<div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px; border-bottom: 2px solid #2E86C1; padding-bottom: 10px;">
    {f'<img src="{img_b64}" height="50">' if img_b64 else ''}
    <h1 style="color: #2E86C1; margin:0; font-size: 24px;">Roteirizador Tecnolab V9.8</h1>
</div>""", unsafe_allow_html=True)

with st.sidebar:
    st.header("📍 Configuração")
    tipo_calc = st.selectbox("Estratégia de Rota:", ["Manter Ordem (Lista)", "Otimizar Caminho (IA)"])
    ceps_in = [st.text_input(f"Parada {i+1}:", key=f"c98_{i}") for i in range(5)]
    ceps_validos = [c for c in ceps_in if c.strip()]
    btn = st.button("🚀 Calcular Rota", use_container_width=True)

# --- 5. LÓGICA ---
if btn and ceps_validos:
    with st.spinner("Calculando distâncias e tempos..."):
        pontos = [get_coords_cep(c, ors_client) for c in ceps_validos if get_coords_cep(c, ors_client)]
        
        if pontos:
            u_base = selecionar_melhor_unidade(pontos[0], unidades, ors_client)
            coords_base = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pontos] + [[u_base['lon'], u_base['lat']]]
            labels_base = [u_base['nome']] + [f"{p['endereco']} ({p['cep']})" for p in pontos] + [f"Retorno: {u_base['nome']}"]
            
            geo_camada = []
            tabela_dados = []
            soma_km = 0
            soma_tempo = 0

            # --- FLUXO 1: ORDEM FIXA ---
            if tipo_calc == "Manter Ordem (Lista)":
                for i in range(len(coords_base) - 1):
                    res = ors_client.directions(coordinates=[coords_base[i], coords_base[i+1]], profile='driving-car', format='geojson')
                    s = res['features'][0]['properties']['summary']
                    dist_km = round(s['distance']/1000, 2)
                    tempo_min = round(s['duration']/60, 1)
                    
                    soma_km += s['distance']
                    soma_tempo += s['duration']
                    geo_camada.extend([[p[1], p[0]] for p in res['features'][0]['geometry']['coordinates']])
                    
                    tabela_dados.append({
                        "Trecho": i + 1,
                        "Origem": labels_base[i],
                        "Destino": labels_base[i+1],
                        "Distância": f"{dist_km} km",
                        "Tempo Est.": f"{tempo_min} min"
                    })

            # --- FLUXO 2: OTIMIZAÇÃO IA ---
            else:
                res = ors_client.directions(coordinates=coords_base, profile='driving-car', format='geojson', optimize_waypoints=True)
                ordem_ia = res['metadata']['query']['waypoint_order']
                indices = [0] + [i + 1 for i in ordem_ia] + [len(coords_base)-1]
                labels_otimizado = [labels_base[i] for i in indices]
                
                soma_km = res['features'][0]['properties']['summary']['distance']
                soma_tempo = res['features'][0]['properties']['summary']['duration']
                geo_camada = [[p[1], p[0]] for p in res['features'][0]['geometry']['coordinates']]
                
                segmentos = res['features'][0]['properties']['segments']
                for i, s in enumerate(segmentos):
                    tabela_dados.append({
                        "Trecho": i + 1,
                        "Origem": labels_otimizado[i],
                        "Destino": labels_otimizado[i+1],
                        "Distância": f"{round(s['distance']/1000, 2)} km",
                        "Tempo Est.": f"{round(s['duration']/60, 1)} min"
                    })

            st.session_state.res_v98 = {
                "unidade": u_base, "km": round(soma_km/1000, 2), "min": int(soma_tempo/60),
                "geo": geo_camada, "tabela": tabela_dados, "pontos": pontos, "modo": tipo_calc
            }

# --- 6. DISPLAY ---
if st.session_state.res_v98:
    r = st.session_state.res_v98
    
    col_inf, col_map = st.columns([1.1, 1])
    with col_inf:
        st.subheader("📋 Itinerário Detalhado")
        st.write(f"Modo: **{r['modo']}** | Distância Total: **{r['km']} km**")
        st.dataframe(pd.DataFrame(r['tabela']), use_container_width=True, hide_index=True)
        
        csv = pd.DataFrame(r['tabela']).to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 Baixar Planilha de Rota", csv, "itinerario_tecnolab.csv", "text/csv", use_container_width=True)
        
        if st.button("🗑️ Limpar Mapa"): 
            st.session_state.res_v98 = None
            st.rerun()
    
    with col_map:
        st.subheader("🗺️ Mapa da Rota")
        m = folium.Map(location=[r['unidade']['lat'], r['unidade']['lon']], zoom_start=12)
        # Marcador Base
        folium.Marker([r['unidade']['lat'], r['unidade']['lon']], icon=folium.Icon(color='green', icon='home'), tooltip=f"BASE: {r['unidade']['nome']}").add_to(m)
        # Marcadores Clientes
        for p in r['pontos']:
            folium.Marker([p['lat'], p['lon']], icon=folium.Icon(color='blue'), tooltip=f"{p['endereco']} | CEP: {p['cep']}").add_to(m)
        # Linha da Rota
        folium.PolyLine(r['geo'], color="#2E86C1", weight=6, opacity=0.8).add_to(m)
        st_folium(m, use_container_width=True, height=500, key="map98")
