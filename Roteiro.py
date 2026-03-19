import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import math
import base64
from PIL import Image
import io
from datetime import datetime

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Roteirizador Tecnolab V9.0", layout="wide", page_icon="🚚")

# --- CSS ADAPTÁVEL (MODO DARK/LIGHT) ---
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    [data-testid="stMetric"] {
        background-color: var(--secondary-background-color);
        padding: 10px 15px;
        border-radius: 10px;
        border: 1px solid rgba(128, 128, 128, 0.2);
    }
    .titulo-roteiro { color: #2E86C1; margin: 0; font-size: 24px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. FUNÇÕES DE SUPORTE ---
def get_image_base64(path):
    try:
        with Image.open(path) as img:
            img = img.convert("RGBA")
            with io.BytesIO() as buffer:
                img.save(buffer, format="PNG")
                return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    except: return None

def get_coords_cep(cep, client_ors):
    try:
        r = requests.get(f"https://viacep.com.br/ws/{cep.replace('-','')}/json/").json()
        if "erro" in r: return None
        logra, cidade = r.get('logradouro', 'N/A'), r.get('localidade', 'N/A')
        # Foco na região de atuação da Tecnolab
        geo = client_ors.pelias_search(text=f"{logra}, {cidade}, SP, Brasil", size=1, focus_point=[-46.55, -23.69])
        if geo and len(geo['features']) > 0:
            c = geo['features'][0]['geometry']['coordinates']
            return {"lat": c[1], "lon": c[0], "endereco": f"{logra}, {r.get('bairro','')}"}
        return None
    except: return None

def selecionar_melhor_unidade(ponto_destino, lista_unidades, client_ors):
    melhor_unid = None
    menor_distancia = float('inf')
    for u in lista_unidades:
        try:
            rota_teste = client_ors.directions(
                coordinates=[[u['lon'], u['lat']], [ponto_destino['lon'], ponto_destino['lat']]],
                profile='driving-car', format='geojson'
            )
            dist_real = rota_teste['features'][0]['properties']['summary']['distance']
            if dist_real < menor_distancia:
                menor_distancia = dist_real
                melhor_unid = u
        except: continue
    return melhor_unid

# --- 3. ASSETS E API ---
img_b64 = get_image_base64("furgao_tecnolab.png")

try:
    api_key = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=api_key)
except:
    st.error("Erro: Configure a ORS_KEY nas Secrets.")
    st.stop()

unidades = [
    {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594},
    {"nome": "Tecno U2", "lat": -23.70601, "lon": -46.54946},
    {"nome": "Tecno U4", "lat": -23.709069, "lon": -46.413002},
    {"nome": "Tecno U5", "lat": -23.65458, "lon": -46.53554},
    {"nome": "Tecno U13", "lat": -23.68791, "lon": -46.62192},
]

if "resultado_rota" not in st.session_state:
    st.session_state.resultado_rota = None

# --- 4. CABEÇALHO ---
st.markdown(f"""<div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px; border-bottom: 2px solid #2E86C1; padding-bottom: 10px;">
    {f'<img src="{img_b64}" height="50">' if img_b64 else ''}
    <h1 class="titulo-roteiro">Roteirizador Tecnolab: Cliente x Unidade</h1>
</div>""", unsafe_allow_html=True)

# --- 5. BARRA LATERAL (CONFIGURAÇÕES) ---
with st.sidebar:
    st.header("📍 Itinerário")
    
    # OPÇÃO DE TIPO DE CÁLCULO
    tipo_calculo = st.radio(
        "Modo de Roteirização:",
        ["Manter Ordem (Lista)", "Otimizar Caminho (IA)"],
        help="Manter Ordem: Segue exatamente a lista de CEPs. Otimizar: A IA decide a ordem mais curta."
    )
    
    ceps_finais = []
    for i in range(5):
        entrada = st.text_input(f"CEP Parada {i+1}:", value="", key=f"cep_v9_{i}")
        if entrada: ceps_finais.append(entrada)
    
    btn_calc = st.button("🚀 Calcular Rota", use_container_width=True)

# --- 6. LÓGICA DE CÁLCULO ---
if btn_calc and ceps_finais:
    with st.spinner("Analisando coordenadas e distâncias reais..."):
        destinos = []
        for cp in ceps_finais:
            info = get_coords_cep(cp, ors_client)
            if info: destinos.append(info)
        
        if destinos:
            # Seleciona unidade de origem com base na rota real até o PRIMEIRO CEP
            u_base = selecionar_melhor_unidade(destinos[0], unidades, ors_client)
            
            coords = [[u_base['lon'], u_base['lat']]]
            labels = [u_base['nome']]
            for d in destinos:
                coords.append([d['lon'], d['lat']])
                labels.append(d['endereco'])
            
            # Retorno à base
            coords.append([u_base['lon'], u_base['lat']])
            labels.append(f"Retorno: {u_base['nome']}")

            # DEFINIÇÃO DA OTIMIZAÇÃO
            otimizar = True if tipo_calculo == "Otimizar Caminho (IA)" else False

            try:
                res_api = ors_client.directions(
                    coordinates=coords, 
                    profile='driving-car', 
                    format='geojson', 
                    optimize_waypoints=otimizar
                )
                
                # Se a API otimizou, precisamos reordenar as labels para a tabela
                indices_ordem = [0] # Origem é sempre 0
                if otimizar:
                    # A API retorna a nova ordem dos waypoints em 'waypoint_order'
                    ordem_ia = res_api['metadata']['query']['waypoint_order']
                    indices_ordem.extend([i + 1 for i in ordem_ia])
                    indices_ordem.append(len(coords)-1) # Destino final
                else:
                    indices_ordem = list(range(len(coords)))

                labels_ordenadas = [labels[i] for i in indices_ordem]
                
                segs = res_api['features'][0]['properties']['segments']
                tabela_data = []
                for idx, s in enumerate(segs):
                    tabela_data.append({
                        "De": labels_ordenadas[idx],
                        "Para": labels_ordenadas[idx+1],
                        "Distância": f"{round(s['distance'] / 1000, 2)} km",
                        "Tempo": f"{round(s['duration'] / 60, 1)} min"
                    })

                st.session_state.resultado_rota = {
                    "unidade": u_base, 
                    "paradas": destinos,
                    "modo": tipo_calculo,
                    "km_total": round(res_api['features'][0]['properties']['summary']['distance'] / 1000, 2),
                    "tempo_total": round(res_api['features'][0]['properties']['summary']['duration'] / 60, 0),
                    "geo": [[p[1], p[0]] for p in res_api['features'][0]['geometry']['coordinates']],
                    "tabela": tabela_data
                }
                st.balloons()
            except Exception as e:
                st.error(f"Erro na API de Roteamento: {e}")

# --- 7. EXIBIÇÃO ---
if st.session_state.resultado_rota:
    r = st.session_state.resultado_rota
    
    # Métricas
    c1, c2, c3 = st.columns(3)
    c1.metric("Origem/Base", r['unidade']['nome'])
    c2.metric("Distância Total", f"{r['km_total']} km")
    c3.metric("Tempo Total", f"{int(r['tempo_total'])} min")

    st.caption(f"Configuração aplicada: **{r['modo']}**")

    col_t, col_m = st.columns([1, 1.2])
    with col_t:
        st.markdown("##### 📋 Cronograma de Viagem")
        st.dataframe(pd.DataFrame(r['tabela']), use_container_width=True, hide_index=True)
        
        if st.button("🗑️ Limpar e Nova Rota", use_container_width=True):
            for k in list(st.session_state.keys()):
                if "cep_v9_" in k: st.session_state[k] = ""
            st.session_state.resultado_rota = None
            st.rerun()

    with col_m:
        st.markdown("##### 🗺️ Visualização do Percurso")
        # Centraliza o mapa no primeiro ponto da rota
        m = folium.Map(location=r['geo'][0], zoom_start=12)
        
        # Marcador da Unidade
        folium.Marker([r['unidade']['lat'], r['unidade']['lon']], 
                      icon=folium.Icon(color='green', icon='home'),
                      tooltip="Unidade Tecnolab").add_to(m)
        
        # Marcadores das Paradas
        for d in r['paradas']:
            folium.Marker([d['lat'], d['lon']], 
                          icon=folium.Icon(color='blue', icon='info-sign'),
                          tooltip=d['endereco']).add_to(m)
        
        # Linha da Rota
        folium.PolyLine(r['geo'], color="#2E86C1", weight=6, opacity=0.8).add_to(m)
        st_folium(m, use_container_width=True, height=500, key="mapa_v9")
else:
    st.info("💡 Insira os CEPs na barra lateral e escolha o modo de cálculo para visualizar o roteiro.")
