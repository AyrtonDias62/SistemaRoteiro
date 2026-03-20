import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from fpdf import FPDF

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V12.1", layout="wide", page_icon="🚚")

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
    modo = st.radio("Configuração da Rota:", ["Ordem da Lista", "Menor Caminho (IA)"])
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"Ponto {i+1}", key=f"c_v121_{i}")
        if c: ceps_raw.append(c)
    btn_calc = st.button("🚀 GERAR ROTEIRO", use_container_width=True, type="primary")

# --- 5. LÓGICA DE PROCESSAMENTO ---
if btn_calc and ceps_raw:
    with st.spinner("Analisando melhor trajeto..."):
        pts_gps = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pts_gps.append(res)
        
        if not pts_gps:
            st.error("Nenhum CEP válido."); st.stop()

        try:
            # --- PASSO 1: DETERMINAR A ORDEM ---
            pts_ordenados = []
            
            if modo == "Menor Caminho (IA)":
                # Criamos a lista de coordenadas para a API Otimizar
                # Importante: A API de directions espera [lon, lat]
                coords_ia = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps] + [[u_base['lon'], u_base['lat']]]
                
                # Chamada de otimização
                res_ia = ors_client.directions(
                    coordinates=coords_ia,
                    profile='driving-car',
                    optimize_waypoints=True # Ativa o algoritmo do caixeiro viajante
                )
                
                # O waypoint_order indica a nova posição dos pontos intermediários
                # Se digitou A, B e a IA diz [1, 0], a nova ordem é B, A.
                ordem_indices = res_ia['metadata']['query']['waypoint_order']
                pts_ordenados = [pts_gps[i] for i in ordem_indices]
            else:
                # Mantém exatamente a ordem digitada nos inputs
                pts_ordenados = pts_gps

            # --- PASSO 2: CÁLCULO REAL POR PERNAS ---
            itinerario = []
            geometria_plot = []
            dist_total_km = 0
            
            # Lista final do percurso: Base -> Pontos -> Base
            percurso_final = [u_base] + pts_ordenados + [u_base]
            
            itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Distancia": "0.0 km", "Tempo": "0 min", "lat": u_base['lat'], "lon": u_base['lon']})

            for i in range(len(percurso_final) - 1):
                p_inicio = percurso_final[i]
                p_destino = percurso_final[i+1]
                
                # Cálculo do trecho individual
                trecho = ors_client.directions(
                    coordinates=[[p_inicio['lon'], p_inicio['lat']], [p_destino['lon'], p_destino['lat']]],
                    profile='driving-car', format='geojson'
                )
                
                summary = trecho['features'][0]['properties']['summary']
                dist_segmento = round(summary['distance'] / 1000, 2)
                tempo_segmento = round(summary['duration'] / 60, 1)
                dist_total_km += dist_segmento
                
                # Geometria para o mapa
                geometria_plot.extend([[c[1], c[0]] for c in trecho['features'][0]['geometry']['coordinates']])
                
                # Label da tabela
                label = "Retorno" if i == len(percurso_final) - 2 else f"{i+1}º"
                
                itinerario.append({
                    "Seq": label,
                    "Destino": f"{p_destino['endereco']} ({p_destino['cep']})",
                    "Distancia": f"{dist_segmento} km",
                    "Tempo": f"{tempo_segmento} min",
                    "lat": p_destino['lat'], "lon": p_destino['lon']
                })

            st.session_state.v121 = {
                "tabela": itinerario,
                "mapa": geometria_plot,
                "total": round(dist_total_km, 2),
                "modo_usado": modo
            }
        except Exception as e:
            st.error(f"Erro no cálculo: {e}")

# --- 6. EXIBIÇÃO ---
if "v121" in st.session_state:
    res = st.session_state.v121
    st.info(f"Modo: **{res['modo_usado']}** | Distância Total: **{res['total']} km**")
    
    c_tabela, c_mapa = st.columns([1, 1.2])
    with c_tabela:
        st.dataframe(pd.DataFrame(res['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        
    with c_mapa:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(res['mapa'], color="blue", weight=5, opacity=0.8).add_to(m)
        for i in res['tabela']:
            base = i['Seq'] in ['Saída', 'Retorno']
            folium.Marker(
                [i['lat'], i['lon']], 
                tooltip=f"{i['Seq']}", 
                icon=folium.Icon(color='green' if base else 'blue', icon='home' if base else 'info-sign')
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
