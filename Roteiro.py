import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V14.2", layout="wide", page_icon="🚚")

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

# --- 3. SETUP API ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro na ORS_KEY."); st.stop()

u_base = {"endereco": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594, "cep": "Matriz"}

# --- 4. INTERFACE ---
with st.sidebar:
    st.header("🚚 Sistema Tecnolab")
    modo = st.selectbox("Comportamento do Roteiro:", [
        "1. Roteiro Travado (Ordem do Input)", 
        "2. Roteiro Inteligente (Circular/Otimizado)"
    ])
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"CEP {i+1}", key=f"cep_v142_{i}")
        if c: ceps_raw.append(c)
    btn = st.button("🚀 GERAR ROTEIRO", use_container_width=True, type="primary")

# --- 5. EXECUÇÃO ---
if btn and ceps_raw:
    pts_gps = []
    for c in ceps_raw:
        res = get_coords_cep(c, ors_client)
        if res: pts_gps.append(res)
    
    if not pts_gps:
        st.error("Nenhum CEP encontrado."); st.stop()

    try:
        itinerario = []
        geometria = []
        dist_total = 0
        
        # --- MODO 2: INTELIGENTE (CIRCULAR) ---
        if "Inteligente" in modo:
            coords = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps]
            res_ia = ors_client.directions(coordinates=coords, profile='driving-car', format='geojson', optimize_waypoints=True)
            
            # Ordem decidida pela IA
            ordem = res_ia.get('metadata', {}).get('query', {}).get('waypoint_order', list(range(len(pts_gps))))
            pts_ordenados = [pts_gps[i] for i in ordem]
            
            # Geometria da ida + segmentos
            geometria = [[c[1], c[0]] for c in res_ia['features'][0]['geometry']['coordinates']]
            segs = res_ia['features'][0]['properties']['segments']
            
            # Cálculo isolado do Retorno (Anti-8km)
            p_fim = pts_ordenados[-1]
            volta = ors_client.directions(coordinates=[[p_fim['lon'], p_fim['lat']], [u_base['lon'], u_base['lat']]], profile='driving-car', format='geojson')
            
            geometria += [[c[1], c[0]] for c in volta['features'][0]['geometry']['coordinates']]
            segs_finais = segs + volta['features'][0]['properties']['segments']
            
        # --- MODO 1: TRAVADO (PEÇA POR PEÇA) ---
        else:
            pts_ordenados = pts_gps
            segs_finais = []
            percurso = [u_base] + pts_ordenados + [u_base]
            for i in range(len(percurso) - 1):
                trecho = ors_client.directions(coordinates=[[percurso[i]['lon'], percurso[i]['lat']], [percurso[i+1]['lon'], percurso[i+1]['lat']]], profile='driving-car', format='geojson')
                segs_finais.append(trecho['features'][0]['properties']['summary'])
                geometria.extend([[c[1], c[0]] for c in trecho['features'][0]['geometry']['coordinates']])

        # --- MONTAGEM UNIFICADA DA TABELA ---
        itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Dist": "0.0 km", "lat": u_base['lat'], "lon": u_base['lon']})
        
        for i, p in enumerate(pts_ordenados):
            d_km = round(segs_finais[i]['distance'] / 1000, 2)
            dist_total += d_km
            itinerario.append({"Seq": f"{i+1}º", "Destino": f"{p['endereco']}", "Dist": f"{d_km} km", "lat": p['lat'], "lon": p['lon']})
        
        d_ret = round(segs_finais[-1]['distance'] / 1000, 2)
        dist_total += d_ret
        itinerario.append({"Seq": "Retorno", "Destino": u_base['endereco'], "Dist": f"{d_ret} km", "lat": u_base['lat'], "lon": u_base['lon']})

        st.session_state.v142 = {"tabela": itinerario, "mapa": geometria, "total": round(dist_total, 2)}

    except Exception as e:
        st.error(f"Erro: {e}")

# --- 6. EXIBIÇÃO ---
if "v142" in st.session_state:
    r = st.session_state.v142
    st.subheader(f"🏁 Total: {r['total']} km")
    
    col1, col2 = st.columns([1, 1.2])
    with col1:
        st.dataframe(pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
    
    with col2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(r['mapa'], color="blue" if "Travado" in modo else "red", weight=5).add_to(m)
        
        # Marcadores garantidos
        for p in r['tabela']:
            is_base = p['Seq'] in ['Saída', 'Retorno']
            folium.Marker(
                [p['lat'], p['lon']], 
                tooltip=p['Seq'],
                icon=folium.Icon(color='green' if is_base else 'blue', icon='info-sign')
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
