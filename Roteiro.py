import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V14.0", layout="wide", page_icon="🚚")

# --- 2. FUNÇÃO DE COORDENADAS ---
@st.cache_data(show_spinner=False)
def get_coords_cep(cep, _ors_client):
    try:
        clean_cep = str(cep).replace('-', '').replace(' ', '').strip()
        r = requests.get(f"https://viacep.com.br/ws/{clean_cep}/json/").json()
        if "erro" in r: return None
        logra = f"{r.get('logradouro')}, {r.get('bairro')}"
        query = f"{logra}, {r.get('localidade')}, {clean_cep}, Brasil"
        geo = _ors_client.pelias_search(text=query, size=1)
        if geo and len(geo['features']) > 0:
            c = geo['features'][0]['geometry']['coordinates']
            return {"lat": c[1], "lon": c[0], "endereco": logra, "cep": clean_cep}
    except: return None

# --- 3. SETUP ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro na ORS_KEY."); st.stop()

u_base = {"endereco": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594, "cep": "Matriz"}

# --- 4. INTERFACE ---
with st.sidebar:
    st.header("🚚 Sistema Tecnolab")
    modo = st.selectbox("Escolha o Comportamento:", ["1. Roteiro Travado (Ordem do Input)", "2. Roteiro Inteligente (Otimizado/Circular)"])
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"CEP {i+1}", key=f"c_v14_{i}")
        if c: ceps_raw.append(c)
    btn = st.button("🚀 CALCULAR AGORA", use_container_width=True, type="primary")

# --- 5. EXECUÇÃO ---
if btn and ceps_raw:
    pts_gps = []
    for c in ceps_raw:
        res = get_coords_cep(c, ors_client)
        if res: pts_gps.append(res)
    
    if not pts_gps:
        st.error("Nenhum CEP válido."); st.stop()

    try:
        # --- ESTRUTURA B: OTIMIZADO (O CAMINHO CIRCULAR DAS VERSÕES INICIAIS) ---
        if "Inteligente" in modo:
            # Fazemos uma única chamada "mestra" para a API organizar tudo
            coords_full = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps] + [[u_base['lon'], u_base['lat']]]
            rota_mestra = ors_client.directions(
                coordinates=coords_full,
                profile='driving-car',
                format='geojson',
                optimize_waypoints=True # A inteligência circular volta aqui
            )
            
            # Reconstruímos a tabela baseada na ordem que a IA decidiu
            ordem_ia = rota_mestra['metadata']['query']['waypoint_order']
            pts_finais = [pts_gps[i] for i in ordem_ia]
            geometria = [[c[1], c[0]] for c in rota_mestra['features'][0]['geometry']['coordinates']]
            segs = rota_mestra['features'][0]['properties']['segments']
            dist_total = round(rota_mestra['features'][0]['properties']['summary']['distance'] / 1000, 2)
        
        # --- ESTRUTURA A: TRAVADO (PEÇA POR PEÇA) ---
        else:
            pts_finais = pts_gps
            geometria = []
            segs = []
            dist_total = 0
            percurso = [u_base] + pts_finais + [u_base]
            
            for i in range(len(percurso) - 1):
                trecho = ors_client.directions(
                    coordinates=[[percurso[i]['lon'], percurso[i]['lat']], [percurso[i+1]['lon'], percurso[i+1]['lat']]],
                    profile='driving-car', format='geojson'
                )
                sumario = trecho['features'][0]['properties']['summary']
                segs.append(sumario) # Simulamos o formato de segmentos
                geometria.extend([[c[1], c[0]] for c in trecho['features'][0]['geometry']['coordinates']])
                dist_total += sumario['distance']
            dist_total = round(dist_total / 1000, 2)

        # --- MONTAGEM DA TABELA (COMUM PARA OS DOIS, MAS DADOS DIFERENTES) ---
        itinerario = []
        itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Distancia": "0.0 km", "lat": u_base['lat'], "lon": u_base['lon']})
        
        for i, p in enumerate(pts_finais):
            d_km = round(segs[i]['distance'] / 1000, 2)
            itinerario.append({
                "Seq": f"{i+1}º",
                "Destino": f"{p['endereco']} ({p['cep']})",
                "Distancia": f"{d_km} km",
                "lat": p['lat'], "lon": p['lon']
            })
        
        # KM de Retorno (Sempre o último segmento da lista)
        d_ret = round(segs[-1]['distance'] / 1000, 2)
        itinerario.append({"Seq": "Retorno", "Destino": u_base['endereco'], "Distancia": f"{d_ret} km", "lat": u_base['lat'], "lon": u_base['lon']})

        st.session_state.v14 = {"tabela": itinerario, "mapa": geometria, "total": dist_total}

    except Exception as e:
        st.error(f"Falha: {e}")

# --- 6. EXIBIÇÃO ---
if "v14" in st.session_state:
    r = st.session_state.v14
    st.subheader(f"Total da Rota: {r['total']} km")
    col1, col2 = st.columns([1, 1.2])
    with col1:
        st.dataframe(pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
    with col2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(r['mapa'], color="blue" if "Ordem" in modo else "red", weight=5).add_to(m)
        for i in r['tabela']:
            folium.Marker([i['lat'], i['lon']], tooltip=i['Seq']).add_to(m)
        st_folium(m, use_container_width=True, height=500)
