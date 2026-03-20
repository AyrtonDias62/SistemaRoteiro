import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from fpdf import FPDF

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V13.2", layout="wide", page_icon="🚚")

# --- 2. FUNÇÕES ---
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
    st.header("🚚 Painel Tecnolab")
    modo = st.radio("Configuração da Rota:", ["Manter Ordem Digitada", "Otimizar Caminho (IA)"])
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"Ponto {i+1}", key=f"c_v132_{i}")
        if c: ceps_raw.append(c)
    btn_calc = st.button("🚀 GERAR ROTEIRO", use_container_width=True, type="primary")

# --- 5. LÓGICA V13.2 ---
if btn_calc and ceps_raw:
    with st.spinner("IA recalculando logística..."):
        pts_gps = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pts_gps.append(res)
        
        if not pts_gps:
            st.error("Nenhum CEP válido."); st.stop()

        try:
            # DETERMINAÇÃO DA ORDEM
            pts_ordenados = []
            
            if modo == "Otimizar Caminho (IA)":
                # Usamos o endpoint de DIRECTIONS para extrair a ordem otimizada
                # SEM repetir a base no final para evitar o erro de waypoint
                coords_input = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps]
                
                res_ia = ors_client.directions(
                    coordinates=coords_input,
                    profile='driving-car',
                    optimize_waypoints=True
                )
                
                # Extração da ordem sugerida pela IA
                if 'waypoint_order' in res_ia['metadata']['query']:
                    # A ordem retornada ignora o ponto 0 (base). 
                    # Se retornar [1, 0], significa que o ponto 2 da lista deve ser o 1º.
                    ordem_ia = res_ia['metadata']['query']['waypoint_order']
                    pts_ordenados = [pts_gps[i] for i in ordem_ia]
                    st.sidebar.success("✅ Rota Otimizada pela IA")
                else:
                    pts_ordenados = pts_gps
                    st.sidebar.warning("⚠️ IA manteve a ordem original")
            else:
                pts_ordenados = pts_gps
                st.sidebar.info("📌 Seguindo ordem da lista")

            # CÁLCULO INDIVIDUAL (ISOLAMENTO ANTI-8KM)
            itinerario = []
            geometria_total = []
            km_total = 0
            percurso_final = [u_base] + pts_ordenados + [u_base]
            
            itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Distancia": "0.0 km", "Tempo": "0 min", "lat": u_base['lat'], "lon": u_base['lon']})

            for i in range(len(percurso_final) - 1):
                p_ini, p_fim = percurso_final[i], percurso_final[i+1]
                
                # Chamada 100% isolada
                trecho = ors_client.directions(
                    coordinates=[[p_ini['lon'], p_ini['lat']], [p_fim['lon'], p_fim['lat']]],
                    profile='driving-car', format='geojson'
                )
                
                sumario = trecho['features'][0]['properties']['summary']
                d_km = round(sumario['distance'] / 1000, 2)
                t_min = round(sumario['duration'] / 60, 1)
                km_total += d_km
                
                geometria_total.extend([[c[1], c[0]] for c in trecho['features'][0]['geometry']['coordinates']])
                
                label = "Retorno" if i == len(percurso_final) - 2 else f"{i+1}ª Parada"
                itinerario.append({
                    "Seq": label,
                    "Destino": f"{p_fim['endereco']} ({p_fim.get('cep', '')})",
                    "Distancia": f"{d_km} km",
                    "Tempo": f"{t_min} min",
                    "lat": p_fim['lat'], "lon": p_fim['lon']
                })

            st.session_state.v132 = {"tabela": itinerario, "mapa": geometria_total, "total": round(km_total, 2)}
        except Exception as e:
            st.error(f"Erro técnico: {e}")

# --- 6. EXIBIÇÃO ---
if "v132" in st.session_state:
    res = st.session_state.v132
    st.markdown(f"### 🚩 Total da Rota: {res['total']} km")
    
    col1, col2 = st.columns([1, 1.3])
    with col1:
        st.dataframe(pd.DataFrame(res['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
    with col2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(res['mapa'], color="blue", weight=5).add_to(m)
        for i in res['tabela']:
            base = i['Seq'] in ['Saída', 'Retorno']
            folium.Marker([i['lat'], i['lon']], tooltip=i['Seq'], icon=folium.Icon(color='green' if base else 'blue')).add_to(m)
        st_folium(m, use_container_width=True, height=500)
