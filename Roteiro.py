import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from datetime import datetime

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Logístico V7", layout="wide")

try:
    api_key = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=api_key)
except Exception as e:
    st.error("Erro: Configure a ORS_KEY nas Secrets.")

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

# --- FUNÇÕES AUXILIARES ---
def get_coords_cep(cep):
    """Busca coordenadas via ViaCEP + ORS Geocoding"""
    r = requests.get(f"https://viacep.com.br/ws/{cep.replace('-','')}/json/").json()
    if "erro" in r: return None
    logra, cidade = r.get('logradouro', ''), r.get('localidade', '')
    geo = ors_client.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
    if geo and len(geo['features']) > 0:
        c = geo['features'][0]['geometry']['coordinates']
        return {"lat": c[1], "lon": c[0], "endereco": f"{logra}, {r.get('bairro')}"}
    return None

def dist_reta(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2) # Simples para ordenação

# --- INTERFACE ---
st.title("🚚 Planejador de Roteiros Multi-Paradas")

with st.sidebar:
    st.header("Entrada de Dados")
    st.write("Insira até 5 CEPs para o roteiro:")
    ceps_input = []
    for i in range(5):
        c = st.text_input(f"CEP Destino {i+1}:", key=f"cep_{i}")
        if c: ceps_input.append(c)
    
    btn_gerar = st.button("Gerar Melhor Rota", use_container_width=True)

if btn_gerar and ceps_input:
    lista_destinos = []
    with st.spinner("Localizando endereços..."):
        for c in ceps_input:
            info = get_coords_cep(c)
            if info: lista_destinos.append(info)
    
    if lista_destinos:
        # 1. Encontrar a unidade mais próxima do primeiro destino para ser a base
        primeiro = lista_destinos[0]
        unidade_base = min(unidades, key=lambda u: (u['lat']-primeiro['lat'])**2 + (u['lon']-primeiro['lon'])**2)
        
        # 2. Montar lista de coordenadas para o ORS (Início -> Paradas -> Fim)
        # Formato ORS: [[lon, lat], [lon, lat]...]
        coords_rota = [[unidade_base['lon'], unidade_base['lat']]]
        for d in lista_destinos:
            coords_rota.append([d['lon'], d['lat']])
        coords_rota.append([unidade_base['lon'], unidade_base['lat']]) # Volta para base

        try:
            with st.spinner("Otimizando trajeto..."):
                # Chamada de Directions com múltiplas coordenadas
                rota_res = ors_client.directions(
                    coordinates=coords_rota,
                    profile='driving-car',
                    format='geojson',
                    optimize_waypoints=True # O ORS tenta organizar a melhor ordem
                )
                
                dist_total = round(rota_res['features'][0]['properties']['summary']['distance'] / 1000, 2)
                tempo_total = round(rota_res['features'][0]['properties']['summary']['duration'] / 60, 0)
                caminho_geom = [[p[1], p[0]] for p in rota_res['features'][0]['geometry']['coordinates']]

            # --- EXIBIÇÃO ---
            col1, col2 = st.columns([1, 2])
            
            with col1:
                st.success(f"**Unidade de Partida:** {unidade_base['nome']}")
                st.metric("Distância Total do Roteiro", f"{dist_total} km")
                st.metric("Tempo Estimado (sem paradas)", f"{int(tempo_total)} min")
                
                st.write("📍 **Sequência do Percurso:**")
                st.write(f"1. 🏠 Saída: {unidade_base['nome']}")
                for i, d in enumerate(lista_destinos):
                    st.write(f"{i+2}. 📦 {d['endereco']}")
                st.write(f"{len(lista_destinos)+2}. 🏁 Retorno: {unidade_base['nome']}")

                if st.button("🎈 Finalizar e Salvar Roteiro"):
                    st.balloons()
            
            with col2:
                m = folium.Map(location=[unidade_base['lat'], unidade_base['lon']], zoom_start=12)
                
                # Marcador da Base
                folium.Marker([unidade_base['lat'], unidade_base['lon']], 
                              icon=folium.Icon(color='green', icon='home'), 
                              tooltip="BASE DE PARTIDA/RETORNO").add_to(m)
                
                # Marcadores dos Destinos
                for i, d in enumerate(lista_destinos):
                    folium.Marker([d['lat'], d['lon']], 
                                  icon=folium.Icon(color='blue', icon='shopping-cart'),
                                  popup=d['endereco'],
                                  tooltip=f"Parada {i+1}").add_to(m)
                
                # Linha da Rota Completa
                folium.PolyLine(caminho_geom, color="red", weight=4, opacity=0.7).add_to(m)
                
                st_folium(m, use_container_width=True, height=600)

        except Exception as e:
            st.error(f"Erro ao calcular rota: {e}")
    else:
        st.error("Nenhum CEP válido encontrado.")
else:
    st.info("Aguardando inserção de CEPs na barra lateral para calcular o roteiro.")
