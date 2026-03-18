import streamlit as st
import pandas as pd
import math
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from datetime import datetime

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Sistema Logístico V6.5 - Log Full", layout="wide")

# Inicialização do Cliente de Mapas (ORS)
try:
    api_key = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=api_key)
except Exception as e:
    st.error("Erro: Configure a ORS_KEY nas Secrets.")

# --- LOGIN SIMPLES ---
if "autenticado" not in st.session_state:
    st.title("🔐 Acesso ao Sistema")
    senha = st.text_input("Digite a senha de acesso:", type="password")
    if st.button("Entrar"):
        if senha == "123456": 
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.stop()

# --- BASE DE UNIDADES ---
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

def calcular_distancia_reta(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return round(R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a))), 2)

# --- INTERFACE ---
st.title("📍 Painel Logístico Profissional")

if 'historico' not in st.session_state:
    st.session_state['historico'] = []

cep = st.text_input("CEP do Cliente:", placeholder="Ex: 09010-000")

if cep:
    r = requests.get(f"https://viacep.com.br/ws/{cep.replace('-','')}/json/").json()
    
    if "erro" not in r:
        logra, bairro, cidade = r.get('logradouro','N/A'), r.get('bairro','N/A'), r.get('localidade','N/A')
        st.info(f"📍 Endereço: {logra} - {bairro}, {cidade}")

        try:
            # Busca Coordenadas Reforçada
            geo_res = ors_client.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
            if geo_res and len(geo_res['features']) > 0:
                coords = geo_res['features'][0]['geometry']['coordinates']
                lat_c, lon_c = coords[1], coords[0]
            else:
                geo_cep = ors_client.pelias_search(text=f"{cep}, Brasil", size=1)
                coords = geo_cep['features'][0]['geometry']['coordinates']
                lat_c, lon_c = coords[1], coords[0]
            
            # Trava de Segurança 150km
            if calcular_distancia_reta(lat_c, lon_c, -23.6912, -46.5594) > 150:
                geo_fix = ors_client.pelias_search(text=f"{cep}, Brasil", size=1)
                coords_f = geo_fix['features'][0]['geometry']['coordinates']
                lat_c, lon_c = coords_f[1], coords_f[0]

            # Dados comparativos
            for u in unidades:
                u['Dist. Reta (km)'] = calcular_distancia_reta(lat_c, lon_c, u['lat'], u['lon'])
            
            df_comparativo = pd.DataFrame(unidades).sort_values('Dist. Reta (km)')
            sugerida_nome = df_comparativo.iloc[0]['nome']

            col_left, col_right = st.columns([1, 1.5])

            with col_left:
                st.subheader("🏁 Atendimento")
                escolha = st.selectbox("Selecione a Unidade:", df_comparativo['nome'].tolist())
                unidade_f = next(item for item in unidades if item["nome"] == escolha)

                # Rota Real
                with st.spinner("Traçando rota..."):
                    route_res = ors_client.directions(
                        coordinates=((lon_c, lat_c), (unidade_f['lon'], unidade_f['lat'])),
                        profile='driving-car', format='geojson'
                    )
                    dist_real = round(route_res['features'][0]['properties']['summary']['distance'] / 1000, 2)
                    caminho = [[p[1], p[0]] for p in route_res['features'][0]['geometry']['coordinates']]

                st.metric("Distância Real (Ruas)", f"{dist_real} km")
                
                if st.button("✅ Gravar e Finalizar", use_container_width=True):
                    # GRAVAÇÃO COMPLETA NO LOG
                    st.session_state['historico'].insert(0, {
                        "Horário": datetime.now().strftime("%H:%M:%S"),
                        "CEP": cep,
                        "Endereço": f"{logra}, {bairro}",
                        "Cidade": cidade,
                        "Unid. Sugerida": sugerida_nome,
                        "Unid. Escolhida": escolha,
                        "Distância KM": dist_real,
                        "Desvio KM": round(dist_real - df_comparativo.iloc[0]['Dist. Reta (km)'], 2)
                    })
                    st.balloons()
                    st.success("Dados salvos com sucesso!")

                st.divider()
                st.subheader("📊 Opções (Linha Reta)")
                st.dataframe(df_comparativo[['nome', 'Dist. Reta (km)']], use_container_width=True, hide_index=True)

            with col_right:
                m = folium.Map(location=[lat_c, lon_c], zoom_start=12)
                folium.Marker([lat_c, lon_c], icon=folium.Icon(color='red', icon='home'), tooltip="Cliente").add_to(m)
                
                # Outras unidades como pontos leves com NOME no tooltip
                for u in unidades:
                    if u['nome'] != escolha:
                        folium.CircleMarker(
                            location=[u['lat'], u['lon']],
                            radius=6, color='gray', fill=True, fill_opacity=0.5,
                            tooltip=u['nome']
                        ).add_to(m)

                # Unidade Selecionada
                folium.Marker([unidade_f['lat'], unidade_f['lon']], icon=folium.Icon(color='green'), tooltip=f"Destino: {escolha}").add_to(m)
                folium.PolyLine(caminho, color="#2E86C1", weight=5, opacity=0.8).add_to(m)
                
                m.fit_bounds([[lat_c, lon_c], [unidade_f['lat'], unidade_f['lon']]])
                st_folium(m, use_container_width=True, height=600, key="mapa_final")

        except Exception as e:
            st.error(f"Erro: {e}")
    else:
        st.error("CEP não encontrado.")

# EXIBIÇÃO DO LOG AMPLIADO
if st.session_state.get('historico'):
    st.divider()
    st.subheader("📝 Relatório Detalhado da Sessão")
    st.dataframe(pd.DataFrame(st.session_state['historico']), use_container_width=True)
