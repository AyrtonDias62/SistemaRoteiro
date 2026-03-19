import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from datetime import datetime
import math
import base64
from PIL import Image
import io

# --- CONFIGURAÇÃO ---
st.set_page_config(
    page_title="Roteirizador Tecnolab3",
    layout="wide",
    page_icon="🚛" # Ícone da aba do navegador
)

# --- FUNÇÃO PARA CARREGAR IMAGEM EM BASE64 (PARA CSS/ÍCONES) ---
def get_image_base64(path):
    with Image.open(path) as img:
        img = img.convert("RGBA")
        with io.BytesIO() as buffer:
            img.save(buffer, format="PNG")
            img_str = base64.b64encode(buffer.getvalue()).decode()
            return f"data:image/png;base64,{img_str}"

# Tenta carregar a imagem do furgão. Substitua pelo nome real do seu arquivo.
try:
    # 1. TÍTULO INTEGRADO COM O FURGÃO (HTML/CSS EM UMA LINHA)
    if img_b64:
        # Ajustamos o tamanho (height="32") para ficar da altura de um título padrão (h2)
        # E usamos flexbox para alinhar perfeitamente o ícone com o texto.
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 20px;">
                <img src="{img_b64}" height="32" style="margin-top: -2px;">
                <h2 style="color: #2E86C1; margin: 0; padding: 0;">Painel de Roteirização Tecnolab3</h2>
            </div>
            """, 
            unsafe_allow_html=True
        )
    else:
        # Fallback caso a imagem não carregue
        st.title("Painel de Roteirização Tecnolab3")
    
    st.divider()

except:
    st.error("Erro: Verifique se o arquivo 'furgao_tecnolab3.png' está na mesma pasta do código.")
    img_b64 = None

# --- INICIALIZAÇÃO DA API (ORS) ---
try:
    api_key = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=api_key)
except Exception as e:
    st.error("Erro: Configure a ORS_KEY nas Secrets.")
    st.stop()

# --- UNIDADES TECNOLAB3 ---
unidades = [
    {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594},
    {"nome": "Tecno São Caetano", "lat": -23.61659, "lon": -46.56845},
    {"nome": "Tecno Santo André", "lat": -23.65458, "lon": -46.53554},
    # Adicione as outras unidades que quiser aqui
]

if "resultado_rota" not in st.session_state:
    st.session_state.resultado_rota = None

# --- FUNÇÃO CEP ---
def get_coords_cep(cep):
    # ViaCEP para endereço em texto
    r = requests.get(f"https://viacep.com.br/ws/{cep.replace('-','')}/json/").json()
    if "erro" in r: return None
    logra, bairro, cidade = r.get('logradouro', 'N/A'), r.get('bairro', 'N/A'), r.get('localidade', 'N/A')
    
    # ORS Pelias para Geocoding
    geo = ors_client.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
    if geo and len(geo['features']) > 0:
        c = geo['features'][0]['geometry']['coordinates']
        return {"lat": c[1], "lon": c[0], "endereco": f"{logra}, {bairro}"}
    return None

# ==============================================================================
# --- INTERFACE ---
# ==============================================================================

# 1. TÍTULO COM O FURGÃO AO LADO (HTML/CSS)
t1, t2 = st.columns([0.15, 1])
with t1:
    if img_b64:
        st.markdown(f'<img src="{img_b64}" width="120" style="margin-top: -30px;">', unsafe_allow_html=True)
with t2:
    st.markdown('<h1 style="color: #2E86C1;">Painel de Roteirização Profissional</h1>', unsafe_allow_html=True)

st.divider()

with st.sidebar:
    st.header("📋 Novo Roteiro")
    ceps_input = []
    for i in range(5):
        c = st.text_input(f"Ponto {i+1} (CEP):", key=f"cep_v74_{i}")
        if c: ceps_input.append(c)
    
    if st.button("Planejar Percurso Tecnolab", use_container_width=True):
        if ceps_input:
            with st.spinner("Analisando distâncias e trânsito..."):
                lista_destinos = []
                for c in ceps_input:
                    info = get_coords_cep(c)
                    if info: lista_destinos.append(info)
                
                if lista_destinos:
                    # Unidade mais próxima
                    p1 = lista_destinos[0]
                    unid_base = min(unidades, key=lambda u: (u['lat']-p1['lat'])**2 + (u['lon']-p1['lon'])**2)
                    
                    # Coordenadas e Labels (Unidade -> Clientes -> Unidade)
                    coords_rota = [[unid_base['lon'], unid_base['lat']]]
                    nomes_labels = [unid_base['nome']]
                    for d in lista_destinos:
                        coords_rota.append([d['lon'], d['lat']])
                        nomes_labels.append(d['endereco'])
                    coords_rota.append([unid_base['lon'], unid_base['lat']])
                    nomes_labels.append(f"🏁 Retorno: {unid_base['nome']}")

                    rota_res = ors_client.directions(
                        coordinates=coords_rota, profile='driving-car', format='geojson', optimize_waypoints=True
                    )
                    
                    segments = rota_res['features'][0]['properties']['segments']
                    tabela_detalhada = []
                    for idx, seg in enumerate(segments):
                        origem = nomes_labels[idx].replace(", São Bernardo do Campo", "")
                        destino = nomes_labels[idx+1].replace(", São Bernardo do Campo", "")
                        tabela_detalhada.append({
                            "Origem": origem, "Destino": destino, "KM": round(seg['distance'] / 1000, 2), "Tempo Est.": f"{round(seg['duration'] / 60, 1)} min"
                        })

                    st.session_state.resultado_rota = {
                        "unidade": unid_base,
                        "destinos": lista_destinos,
                        "distancia_total": round(rota_res['features'][0]['properties']['summary']['distance'] / 1000, 2),
                        "tempo_total": round(rota_res['features'][0]['properties']['summary']['duration'] / 60, 0),
                        "caminho": [[p[1], p[0]] for p in rota_res['features'][0]['geometry']['coordinates']],
                        "tabela": tabela_detalhada
                    }
                else:
                    st.error("Erro ao validar os CEPs.")

# --- EXIBIÇÃO ---
if st.session_state.resultado_rota:
    res = st.session_state.resultado_rota
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Unidade de Apoio", res['unidade']['nome'])
    m2.metric("Total da Rota", f"{res['distancia_total']} km")
    m3.metric("Tempo Total Estimado", f"{int(res['tempo_total'])} min")

    st.divider()
    
    col_table, col_map = st.columns([1, 1])

    with col_table:
        st.subheader("📋 Relatório de Viagem Detalhado")
        df = pd.DataFrame(res['tabela'])
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        # --- MARCA D'ÁGUA EMBAIXO DA TABELA (CSS) ---
        if img_b64:
            st.markdown(
                f"""
                <div style="width: 100%; text-align: center; margin-top: 50px; opacity: 0.15; filter: grayscale(100%);">
                    <img src="{img_b64}" width="400">
                    <p style="color: #666; margin-top: -10px;">Sistema Roteirizador Tecnolab3</p>
                </div>
                """, 
                unsafe_allow_html=True
            )

        if st.button("🗑️ Resetar Sistema", use_container_width=True):
            st.session_state.resultado_rota = None
            st.rerun()

    with col_map:
        m = folium.Map(location=[res['unidade']['lat'], res['unidade']['lon']], zoom_start=12)
        folium.Marker([res['unidade']['lat'], res['unidade']['lon']], icon=folium.Icon(color='green', icon='home'), tooltip="Unidade Tecnolab").add_to(m)
        for i, d in enumerate(res['destinos']):
            folium.Marker([d['lat'], d['lon']], icon=folium.Icon(color='blue'), tooltip=f"Parada {i+1}: {d['endereco']}").add_to(m)
        folium.PolyLine(res['caminho'], color="#27AE60", weight=5, opacity=0.8).add_to(m)
        st_folium(m, use_container_width=True, height=600, key="mapa_tecnolab")

else:
    st.info("Digite os destinos na lateral para traçar a rota da Tecnolab3.")
