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
st.set_page_config(page_title="Roteirizador V7.3 - Tempos e Percursos", layout="wide")

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

if "resultado_rota" not in st.session_state:
    st.session_state.resultado_rota = None

def get_coords_cep(cep):
    r = requests.get(f"https://viacep.com.br/ws/{cep.replace('-','')}/json/").json()
    if "erro" in r: return None
    logra, bairro, cidade = r.get('logradouro', 'N/A'), r.get('bairro', 'N/A'), r.get('localidade', 'N/A')
    # Busca com foco em SBC/SP para evitar erros de cidades homônimas
    geo = ors_client.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
    if geo and len(geo['features']) > 0:
        c = geo['features'][0]['geometry']['coordinates']
        return {"lat": c[1], "lon": c[0], "endereco": f"{logra}, {bairro}"}
    return None

# --- INTERFACE ---
st.title("🚚 Gestão de Rotas: Tempos e Distâncias")

with st.sidebar:
    st.header("Configurar Roteiro")
    st.info("Insira os CEPs na ordem desejada ou deixe que o sistema otimize a sequência.")
    ceps_input = []
    for i in range(5):
        c = st.text_input(f"Parada {i+1} (CEP):", key=f"cep_v73_{i}")
        if c: ceps_input.append(c)
    
    if st.button("Gerar Relatório de Viagem", use_container_width=True):
        if ceps_input:
            with st.spinner("Analisando tráfego e distâncias..."):
                lista_destinos = []
                for c in ceps_input:
                    info = get_coords_cep(c)
                    if info: lista_destinos.append(info)
                
                if lista_destinos:
                    # Define a unidade de saída (mais próxima da 1ª parada)
                    p1 = lista_destinos[0]
                    unid_base = min(unidades, key=lambda u: (u['lat']-p1['lat'])**2 + (u['lon']-p1['lon'])**2)
                    
                    # Monta a lista de pontos (Unidade -> Clientes -> Unidade)
                    coords_rota = [[unid_base['lon'], unid_base['lat']]]
                    nomes_labels = [f"Início: {unid_base['nome']}"]
                    for d in lista_destinos:
                        coords_rota.append([d['lon'], d['lat']])
                        nomes_labels.append(d['endereco'])
                    coords_rota.append([unid_base['lon'], unid_base['lat']])
                    nomes_labels.append(f"Retorno: {unid_base['nome']}")

                    # API Call
                    rota_res = ors_client.directions(
                        coordinates=coords_rota,
                        profile='driving-car',
                        format='geojson',
                        optimize_waypoints=True
                    )
                    
                    # Processa os segmentos (trechos individuais)
                    segments = rota_res['features'][0]['properties']['segments']
                    percursos_detalhados = []
                    for idx, seg in enumerate(segments):
                        percursos_detalhados.append({
                            "Origem": nomes_labels[idx],
                            "Destino": nomes_labels[idx+1],
                            "KM": round(seg['distance'] / 1000, 2),
                            "Tempo Est.": f"{round(seg['duration'] / 60, 1)} min"
                        })

                    st.session_state.resultado_rota = {
                        "unidade": unid_base,
                        "destinos": lista_destinos,
                        "distancia_total": round(rota_res['features'][0]['properties']['summary']['distance'] / 1000, 2),
                        "tempo_total": round(rota_res['features'][0]['properties']['summary']['duration'] / 60, 0),
                        "caminho": [[p[1], p[0]] for p in rota_res['features'][0]['geometry']['coordinates']],
                        "tabela": percursos_detalhados
                    }
                else:
                    st.error("Erro ao validar os CEPs.")

# --- EXIBIÇÃO DOS RESULTADOS ---
if st.session_state.resultado_rota:
    res = st.session_state.resultado_rota
    
    # Resumo Executivo
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Base de Operação", res['unidade']['nome'])
    col_m2.metric("Total da Rota", f"{res['distancia_total']} km")
    col_m3.metric("Tempo em Trânsito", f"{int(res['tempo_total'])} min")

    st.divider()
    
    col_left, col_right = st.columns([1.3, 1])

    with col_left:
        st.subheader("📋 Quadro de Percursos Detalhado")
        df = pd.DataFrame(res['tabela'])
        # Estilizando a tabela para melhor leitura
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        st.warning("⚠️ O tempo estimado não inclui o tempo de permanência em cada cliente.")
        
        if st.button("🗑️ Limpar e Nova Rota", use_container_width=True):
            st.session_state.resultado_rota = None
            st.rerun()

    with col_right:
        st.subheader("🗺️ Mapa do Itinerário")
        m = folium.Map(location=[res['unidade']['lat'], res['unidade']['lon']], zoom_start=12)
        
        # Marcador da Unidade (Base)
        folium.Marker([res['unidade']['lat'], res['unidade']['lon']], 
                      icon=folium.Icon(color='green', icon='home'),
                      tooltip="Ponto de Apoio").add_to(m)
        
        # Marcadores das Paradas
        for i, d in enumerate(res['destinos']):
            folium.Marker([d['lat'], d['lon']], 
                          icon=folium.Icon(color='blue', icon='user'),
                          tooltip=f"Parada {i+1}: {d['endereco']}").add_to(m)
        
        # Desenho da Rota
        folium.PolyLine(res['caminho'], color="#E74C3C", weight=5, opacity=0.8).add_to(m)
        
        st_folium(m, use_container_width=True, height=450, key="mapa_v73")

else:
    st.info("Utilize a barra lateral para inserir os destinos e calcular o tempo de percurso.")
