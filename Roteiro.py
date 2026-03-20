import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V12.2", layout="wide", page_icon="🚚")

# --- 2. FUNÇÃO DE GEOLOCALIZAÇÃO ---
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

# --- 3. SETUP API ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro na ORS_KEY."); st.stop()

u_base = {"endereco": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594, "cep": "Matriz"}

# --- 4. INTERFACE ---
with st.sidebar:
    st.header("🚚 Painel de Controle")
    modo = st.selectbox("Estratégia de Rota:", ["Manter Ordem Digitada", "Otimizar para Menor Caminho"])
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"Ponto {i+1}", key=f"c_v122_{i}")
        if c: ceps_raw.append(c)
    btn_calc = st.button("🚀 GERAR ROTA ISOLADA", use_container_width=True, type="primary")

# --- 5. LÓGICA DE PROCESSAMENTO ISOLADO ---
if btn_calc and ceps_raw:
    with st.spinner("Processando trechos independentes..."):
        # Converter CEPs em Coordenadas
        pts_gps = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pts_gps.append(res)
        
        if not pts_gps:
            st.error("Nenhum CEP válido."); st.stop()

        try:
            # --- FASE 1: DEFINIÇÃO DA ORDEM (SEM CONTAMINAÇÃO) ---
            if modo == "Otimizar para Menor Caminho":
                # Usamos a Matriz de Distância para decidir a ordem manualmente
                all_coords = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps]
                matrix = ors_client.distance_matrix(locations=all_coords, profile='driving-car', metrics=['distance'])
                
                # Distâncias da base (índice 0) para todos os outros
                distancias_da_base = matrix['distances'][0][1:] # Pula a distância da base para ela mesma
                
                # Criar um ranking: Ponto e sua distância da base
                ranking = []
                for idx, d in enumerate(distancias_da_base):
                    ranking.append({"ponto": pts_gps[idx], "dist": d})
                
                # Ordenar o ranking pela menor distância
                ranking_ordenado = sorted(ranking, key=lambda x: x['dist'])
                pts_ordenados = [item['ponto'] for item in ranking_ordenado]
            else:
                pts_ordenados = pts_gps

            # --- FASE 2: CÁLCULO DE PERNAS 100% INDEPENDENTES ---
            itinerario = []
            geometria_total = []
            km_total = 0
            
            # Lista de Saltos: Base -> P1 -> P2 -> ... -> Pn -> Base
            saltos = [u_base] + pts_ordenados + [u_base]
            
            # Linha inicial da tabela
            itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Km Trecho": "0.0", "Tempo": "0", "lat": u_base['lat'], "lon": u_base['lon']})

            for i in range(len(saltos) - 1):
                origem = saltos[i]
                destino = saltos[i+1]
                
                # CHAMADA ISOLADA: Apenas de A para B
                res_trecho = ors_client.directions(
                    coordinates=[[origem['lon'], origem['lat']], [destino['lon'], destino['lat']]],
                    profile='driving-car', format='geojson'
                )
                
                # Extração de dados do trecho único
                dados = res_trecho['features'][0]['properties']['summary']
                d_km = round(dados['distance'] / 1000, 2)
                t_min = round(dados['duration'] / 60, 1)
                km_total += d_km
                
                # Geometria individual
                geometria_total.extend([[c[1], c[0]] for c in res_trecho['features'][0]['geometry']['coordinates']])
                
                # Definir nome da etapa
                label = "Retorno" if i == len(saltos) - 2 else f"{i+1}º Parada"
                
                itinerario.append({
                    "Seq": label,
                    "Destino": f"{destino['endereco']} ({destino.get('cep', '')})",
                    "Km Trecho": f"{d_km} km",
                    "Tempo": f"{t_min} min",
                    "lat": destino['lat'], "lon": destino['lon']
                })

            st.session_state.v122 = {
                "tabela": itinerario,
                "mapa": geometria_total,
                "total": round(km_total, 2)
            }

        except Exception as e:
            st.error(f"Erro no isolamento: {e}")

# --- 6. EXIBIÇÃO ---
if "v122" in st.session_state:
    r = st.session_state.v122
    st.subheader(f"📊 Relatório de Percurso: {r['total']} km")
    
    col_t, col_m = st.columns([1, 1.2])
    with col_t:
        st.dataframe(pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        
    with col_m:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(r['mapa'], color="red", weight=4).add_to(m)
        for i in r['tabela']:
            cor = 'green' if i['Seq'] in ['Saída', 'Retorno'] else 'blue'
            folium.Marker([i['lat'], i['lon']], tooltip=i['Seq'], icon=folium.Icon(color=cor)).add_to(m)
        st_folium(m, use_container_width=True, height=500)
