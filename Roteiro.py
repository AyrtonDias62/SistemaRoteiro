import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from fpdf import FPDF

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V12.0", layout="wide", page_icon="🚚")

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
    modo = st.radio("Logística:", ["Ordem da Lista", "Menor Caminho (IA)"], 
                    help="O 'Menor Caminho' vai embaralhar os CEPs para economizar gasolina.")
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"Ponto {i+1}", key=f"c_v12_{i}")
        if c: ceps_raw.append(c)
    btn_calc = st.button("🚀 CALCULAR ROTA", use_container_width=True, type="primary")

# --- 5. LÓGICA DE PROCESSAMENTO ---
if btn_calc and ceps_raw:
    with st.spinner("Otimizando e calculando trechos..."):
        pts_gps = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pts_gps.append(res)
        
        if not pts_gps:
            st.error("Nenhum CEP válido."); st.stop()

        try:
            # --- PASSO 1: DESCOBRIR A MELHOR ORDEM ---
            pts_ordenados = []
            if modo == "Menor Caminho (IA)":
                coords_otimizar = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps] + [[u_base['lon'], u_base['lat']]]
                res_otimizacao = ors_client.directions(
                    coordinates=coords_otimizar,
                    profile='driving-car',
                    optimize_waypoints=True # Aqui a IA trabalha
                )
                # A API retorna waypoint_order, ex: [1, 0] para dizer que o 2º CEP inserido deve ser o 1º a ser visitado
                ordem_indices = res_otimizacao['metadata']['query']['waypoint_order']
                pts_ordenados = [pts_gps[i] for i in ordem_indices]
            else:
                pts_ordenados = pts_gps

            # --- PASSO 2: CALCULAR PERNA POR PERNA (Para garantir os KMs reais) ---
            itinerario = []
            geometria_completa = []
            dist_total = 0
            
            # Adicionar Saída
            itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Distancia": "0.0 km", "Tempo": "0 min", "lat": u_base['lat'], "lon": u_base['lon']})
            
            percurso = [u_base] + pts_ordenados + [u_base]
            
            for i in range(len(percurso) - 1):
                p_ini, p_fim = percurso[i], percurso[i+1]
                
                trecho = ors_client.directions(
                    coordinates=[[p_ini['lon'], p_ini['lat']], [p_fim['lon'], p_fim['lat']]],
                    profile='driving-car', format='geojson'
                )
                
                info = trecho['features'][0]['properties']['summary']
                d_km = round(info['distance'] / 1000, 2)
                t_min = round(info['duration'] / 60, 1)
                dist_total += d_km
                
                geometria_completa.extend([[c[1], c[0]] for c in trecho['features'][0]['geometry']['coordinates']])
                
                label = "Retorno" if i == len(percurso) - 2 else f"{i+1}º"
                itinerario.append({
                    "Seq": label,
                    "Destino": f"{p_fim['endereco']} ({p_fim['cep']})",
                    "Distancia": f"{d_km} km",
                    "Tempo": f"{t_min} min",
                    "lat": p_fim['lat'], "lon": p_fim['lon']
                })

            st.session_state.v12 = {
                "tabela": itinerario,
                "mapa": geometria_completa,
                "total": round(dist_total, 2)
            }
        except Exception as e:
            st.error(f"Erro: {e}")

# --- 6. EXIBIÇÃO ---
if "v12" in st.session_state:
    r = st.session_state.v119 if "v119" in st.session_state and False else st.session_state.v12
    st.success(f"Caminho calculado: {r['total']} km total.")
    
    col1, col2 = st.columns([1, 1.3])
    with col1:
        st.dataframe(pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
    with col2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(r['mapa'], color="#2E86C1", weight=5).add_to(m)
        for i in r['tabela']:
            base = i['Seq'] in ['Saída', 'Retorno']
            folium.Marker([i['lat'], i['lon']], tooltip=i['Seq'], icon=folium.Icon(color='green' if base else 'blue')).add_to(m)
        st_folium(m, use_container_width=True, height=500)
