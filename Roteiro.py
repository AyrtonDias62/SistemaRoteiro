import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V14.1", layout="wide", page_icon="🚚")

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
    modo = st.selectbox("Escolha o Comportamento:", [
        "1. Roteiro Travado (Ordem do Input)", 
        "2. Roteiro Inteligente (Otimizado/Circular)"
    ])
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"CEP {i+1}", key=f"c_v141_{i}")
        if c: ceps_raw.append(c)
    btn = st.button("🚀 CALCULAR ROTA", use_container_width=True, type="primary")

# --- 5. EXECUÇÃO ---
if btn and ceps_raw:
    pts_gps = []
    for c in ceps_raw:
        res = get_coords_cep(c, ors_client)
        if res: pts_gps.append(res)
    
    if not pts_gps:
        st.error("Nenhum CEP válido."); st.stop()

    try:
        # --- ESTRUTURA B: OTIMIZADO (ESTILO CIRCULAR) ---
        if "Inteligente" in modo:
            # Enviamos Base + Pontos (Sem repetir a base no fim para evitar erro de waypoint)
            coords_full = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps]
            
            rota_mestra = ors_client.directions(
                coordinates=coords_full,
                profile='driving-car',
                format='geojson',
                optimize_waypoints=True
            )
            
            # TRATAMENTO SEGURO DO WAYPOINT_ORDER
            # Se a API não devolver a ordem, usamos a ordem original (0, 1, 2...)
            metadata = rota_mestra.get('metadata', {})
            query_info = metadata.get('query', {})
            ordem_ia = query_info.get('waypoint_order', list(range(len(pts_gps))))
            
            pts_finais = [pts_gps[i] for i in ordem_ia]
            
            # No modo inteligente, precisamos calcular o retorno manualmente para garantir os KMs
            # Então pegamos a geometria da rota mestra e adicionamos a perna de volta
            geometria = [[c[1], c[0]] for c in rota_mestra['features'][0]['geometry']['coordinates']]
            segs_originais = rota_mestra['features'][0]['properties']['segments']
            
            # Cálculo isolado do retorno (Ponto Final -> Base) para evitar os 8km
            p_ultimo = pts_finais[-1]
            volta = ors_client.directions(
                coordinates=[[p_ultimo['lon'], p_ultimo['lat']], [u_base['lon'], u_base['lat']]],
                profile='driving-car', format='geojson'
            )
            
            # Unindo os dados
            geometria += [[c[1], c[0]] for c in volta['features'][0]['geometry']['coordinates']]
            segs = segs_originais + volta['features'][0]['properties']['segments']
            
        # --- ESTRUTURA A: TRAVADO (PEÇA POR PEÇA) ---
        else:
            pts_finais = pts_gps
            geometria = []
            segs = []
            percurso = [u_base] + pts_finais + [u_base]
            
            for i in range(len(percurso) - 1):
                trecho = ors_client.directions(
                    coordinates=[[percurso[i]['lon'], percurso[i]['lat']], [percurso[i+1]['lon'], percurso[i+1]['lat']]],
                    profile='driving-car', format='geojson'
                )
                sumario = trecho['features'][0]['properties']['summary']
                segs.append(sumario)
                geometria.extend([[c[1], c[0]] for c in trecho['features'][0]['geometry']['coordinates']])

        # --- MONTAGEM DA TABELA ---
        itinerario = []
        itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Distancia": "0.0 km", "lat": u_base['lat'], "lon": u_base['lon']})
        
        dist_total_acumulada = 0
        for i, p in enumerate(pts_finais):
            d_m = segs[i]['distance']
            d_km = round(d_m / 1000, 2)
            dist_total_acumulada += d_km
            itinerario.append({
                "Seq": f"{i+1}º",
                "Destino": f"{p['endereco']} ({p['cep']})",
                "Distancia": f"{d_km} km",
                "lat": p['lat'], "lon": p['lon']
            })
        
        d_ret = round(segs[-1]['distance'] / 1000, 2)
        dist_total_acumulada += d_ret
        itinerario.append({"Seq": "Retorno", "Destino": u_base['endereco'], "Distancia": f"{d_ret} km", "lat": u_base['lat'], "lon": u_base['lon']})

        st.session_state.v141 = {
            "tabela": itinerario, 
            "mapa": geometria, 
            "total": round(dist_total_acumulada, 2)
        }

    except Exception as e:
        st.error(f"Erro no processamento: {e}")

# --- 6. EXIBIÇÃO ---
if "v141" in st.session_state:
    r = st.session_state.v141
    st.success(f"### Rota Finalizada: {r['total']} km")
    
    col1, col2 = st.columns([1, 1.2])
    with col1:
        st.dataframe(pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
    with col2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(r['mapa'], color="blue" if "Travado" in modo else "red", weight=5).add_to(m)
        for i in r['tabela']:
            folium.Marker([i['lat'], i['lon']], tooltip=i['Seq']).add_to(m)
        st_folium(m, use_container_width=True, height=500)
