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
st.set_page_config(page_title="Roteirizador Logístico V7.1", layout="wide")

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

# --- MEMÓRIA DO APP (SESSION STATE) ---
if "resultado_rota" not in st.session_state:
    st.session_state.resultado_rota = None

# --- FUNÇÕES ---
def get_coords_cep(cep):
    r = requests.get(f"https://viacep.com.br/ws/{cep.replace('-','')}/json/").json()
    if "erro" in r: return None
    logra, cidade = r.get('logradouro', ''), r.get('localidade', '')
    geo = ors_client.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
    if geo and len(geo['features']) > 0:
        c = geo['features'][0]['geometry']['coordinates']
        return {"lat": c[1], "lon": c[0], "endereco": f"{logra}, {r.get('bairro')}"}
    return None

# --- INTERFACE ---
st.title("🚚 Planejador de Roteiros Multi-Paradas")

with st.sidebar:
    st.header("Entrada de Dados")
    ceps_input = []
    for i in range(5):
        c = st.text_input(f"CEP Destino {i+1}:", key=f"input_cep_{i}")
        if c: ceps_input.append(c)
    
    if st.button("Gerar Melhor Rota", use_container_width=True):
        if ceps_input:
            with st.spinner("Processando roteiro..."):
                lista_destinos = []
                for c in ceps_input:
                    info = get_coords_cep(c)
                    if info: lista_destinos.append(info)
                
                if lista_destinos:
                    # Seleção da Unidade Base (mais próxima do 1º CEP)
                    primeiro = lista_destinos[0]
                    unidade_base = min(unidades, key=lambda u: (u['lat']-primeiro['lat'])**2 + (u['lon']-primeiro['lon'])**2)
                    
                    coords_rota = [[unidade_base['lon'], unidade_base['lat']]]
                    for d in lista_destinos:
                        coords_rota.append([d['lon'], d['lat']])
                    coords_rota.append([unidade_base['lon'], unidade_base['lat']])

                    rota_res = ors_client.directions(
                        coordinates=coords_rota,
                        profile='driving-car',
                        format='geojson',
                        optimize_waypoints=True
                    )
                    
                    # Salva TUDO na memória para não sumir
                    st.session_state.resultado_rota = {
                        "unidade": unidade_base,
                        "destinos": lista_destinos,
                        "distancia": round(rota_res['features'][0]['properties']['summary']['distance'] / 1000, 2),
                        "tempo": round(rota_res['features'][0]['properties']['summary']['duration'] / 60, 0),
                        "caminho": [[p[1], p[0]] for p in rota_res['features'][0]['geometry']['coordinates']]
                    }
                else:
                    st.error("Nenhum CEP válido foi encontrado.")
        else:
            st.warning("Insira pelo menos um CEP.")

# --- EXIBIÇÃO (SÓ APARECE SE HOUVER RESULTADO NA MEMÓRIA) ---
if st.session_state.resultado_rota:
    res = st.session_state.resultado_rota
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.success(f"**Unidade de Partida:** {res['unidade']['nome']}")
        st.metric("Distância Total", f"{res['distancia']} km")
        st.metric("Tempo Estimado", f"{int(res['tempo'])} min")
        
        st.write("📍 **Sequência:**")
        st.caption(f"1. 🏠 Saída: {res['unidade']['nome']}")
        for i, d in enumerate(res['destinos']):
            st.caption(f"{i+2}. 📦 {d['endereco']}")
        st.caption(f"{len(res['destinos'])+2}. 🏁 Retorno: {res['unidade']['nome']}")

        if st.button("🗑️ Limpar Roteiro"):
            st.session_state.resultado_rota = None
            st.rerun()
    
    with col2:
        m = folium.Map(location=[res['unidade']['lat'], res['unidade']['lon']], zoom_start=12)
        folium.Marker([res['unidade']['lat'], res['unidade']['lon']], 
                      icon=folium.Icon(color='green', icon='home')).add_to(m)
        
        for i, d in enumerate(res['destinos']):
            folium.Marker([d['lat'], d['lon']], 
                          icon=folium.Icon(color='blue', icon='shopping-cart'),
                          tooltip=f"Parada {i+1}: {d['endereco']}").add_to(m)
        
        folium.PolyLine(res['caminho'], color="red", weight=4, opacity=0.7).add_to(m)
        st_folium(m, use_container_width=True, height=600, key="mapa_roteiro")
else:
    st.info("Digite os CEPs na lateral e clique em 'Gerar Melhor Rota'.")
