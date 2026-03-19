import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from datetime import datetime
import math

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Logístico V7.2 - Detalhado", layout="wide")

try:
    api_key = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=api_key)
except Exception as e:
    st.error("Erro: Configure a ORS_KEY nas Secrets.")
    st.stop()

# --- UNIDADES ---
unidades = [
    {"nome": "Matriz", "lat": -23.6912, "lon": -46.5594},
    {"nome": "U2", "lat": -23.70601, "lon": -46.54946},
    {"nome": "U4", "lat": -23.709069, "lon": -46.413002},
    {"nome": "U5", "lat": -23.65458, "lon": -46.53554},
    {"nome": "U6", "lat": -23.66669, "lon": -46.45455},
    {"nome": "U7", "lat": -23.66117, "lon": -46.56506},
    {"nome": "U8", "lat": -23.72231, "lon": -46.56675},
    {"nome": "U9", "lat": -23.61659, "lon": -46.56845},
    {"nome": "U10", "lat": -23.6326784, "lon": -46.5021218},
    {"nome": "U11", "lat": -23.65379, "lon": -46.53542},
    {"nome": "U13", "lat": -23.68791, "lon": -46.62192},
    {"nome": "U14", "lat": -23.66884, "lon": -46.45567},
]

# --- MEMÓRIA DO APP ---
if "resultado_rota" not in st.session_state:
    st.session_state.resultado_rota = None

def get_coords_cep(cep):
    r = requests.get(f"https://viacep.com.br/ws/{cep.replace('-','')}/json/").json()
    if "erro" in r: return None
    logra, bairro, cidade = r.get('logradouro', ''), r.get('bairro', ''), r.get('localidade', '')
    geo = ors_client.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
    if geo and len(geo['features']) > 0:
        c = geo['features'][0]['geometry']['coordinates']
        return {"lat": c[1], "lon": c[0], "endereco": f"{logra}, {bairro}"}
    return None

# --- INTERFACE ---
st.title("🚚 Planejador de Roteiros com Detalhamento de Trechos")

with st.sidebar:
    st.header("Entrada de CEPs")
    ceps_input = []
    for i in range(5):
        c = st.text_input(f"CEP Destino {i+1}:", key=f"input_cep_{i}")
        if c: ceps_input.append(c)
    
    if st.button("Calcular Roteiro Completo", use_container_width=True):
        if ceps_input:
            with st.spinner("Calculando e otimizando percurso..."):
                lista_destinos = []
                for c in ceps_input:
                    info = get_coords_cep(c)
                    if info: lista_destinos.append(info)
                
                if lista_destinos:
                    # Unidade mais próxima do primeiro CEP
                    p1 = lista_destinos[0]
                    unid_base = min(unidades, key=lambda u: (u['lat']-p1['lat'])**2 + (u['lon']-p1['lon'])**2)
                    
                    coords_rota = [[unid_base['lon'], unid_base['lat']]]
                    nomes_pontos = [unid_base['nome']]
                    for d in lista_destinos:
                        coords_rota.append([d['lon'], d['lat']])
                        nomes_pontos.append(d['endereco'])
                    coords_rota.append([unid_base['lon'], unid_base['lat']])
                    nomes_pontos.append(f"Retorno {unid_base['nome']}")

                    # Chamada Directions
                    rota_res = ors_client.directions(
                        coordinates=coords_rota,
                        profile='driving-car',
                        format='geojson',
                        optimize_waypoints=True
                    )
                    
                    # Extração de trechos (Segments)
                    segments = rota_res['features'][0]['properties']['segments']
                    detalhes_trechos = []
                    for idx, seg in enumerate(segments):
                        detalhes_trechos.append({
                            "De": nomes_pontos[idx],
                            "Para": nomes_pontos[idx+1],
                            "Distância (km)": round(seg['distance'] / 1000, 2),
                            "Tempo (min)": round(seg['duration'] / 60, 1)
                        })

                    st.session_state.resultado_rota = {
                        "unidade": unid_base,
                        "destinos": lista_destinos,
                        "distancia_total": round(rota_res['features'][0]['properties']['summary']['distance'] / 1000, 2),
                        "tempo_total": round(rota_res['features'][0]['properties']['summary']['duration'] / 60, 0),
                        "caminho_geom": [[p[1], p[0]] for p in rota_res['features'][0]['geometry']['coordinates']],
                        "quadro_trechos": detalhes_trechos
                    }
                else:
                    st.error("Nenhum CEP válido encontrado.")

# --- EXIBIÇÃO ---
if st.session_state.resultado_rota:
    res = st.session_state.resultado_rota
    
    # Métricas de Resumo
    m1, m2, m3 = st.columns(3)
    m1.metric("Unidade Base", res['unidade']['nome'])
    m2.metric("Distância Total", f"{res['distancia_total']} km")
    m3.metric("Tempo Total Estimado", f"{int(res['tempo_total'])} min")

    st.divider()
    
    col_map, col_table = st.columns([1.2, 1])

    with col_table:
        st.subheader("📋 Quadro de Trajetos")
        df_trechos = pd.DataFrame(res['quadro_trechos'])
        st.dataframe(df_trechos, use_container_width=True, hide_index=True)
        
        st.info("💡 Os tempos acima consideram apenas o deslocamento (sem o tempo de parada no cliente).")
        
        if st.button("🗑️ Resetar Sistema"):
            st.session_state.resultado_rota = None
            st.rerun()

    with col_map:
        m = folium.Map(location=[res['unidade']['lat'], res['unidade']['lon']], zoom_start=12)
        folium.Marker([res['unidade']['lat'], res['unidade']['lon']], icon=folium.Icon(color='green', icon='home')).add_to(m)
        
        for i, d in enumerate(res['destinos']):
            folium.Marker([d['lat'], d['lon']], icon=folium.Icon(color='blue'), tooltip=f"Parada {i+1}").add_to(m)
        
        folium.PolyLine(res['caminho_geom'], color="red", weight=4, opacity=0.7).add_to(m)
        st_folium(m, use_container_width=True, height=500, key="mapa_v72")
