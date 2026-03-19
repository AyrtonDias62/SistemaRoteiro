import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V10.6", layout="wide", page_icon="🚚")

# --- 2. FUNÇÕES CORE ---
@st.cache_data(show_spinner=False)
def get_coords_cep(cep, _ors_client):
    try:
        clean_cep = str(cep).replace('-', '').replace(' ', '').strip()
        r = requests.get(f"https://viacep.com.br/ws/{clean_cep}/json/").json()
        
        if "erro" in r:
            query = f"{clean_cep}, Brasil"
            logra_vinc = "CEP " + clean_cep
        else:
            # Forçamos a busca na região de SP para evitar desvios
            logra_vinc = r.get('logradouro')
            query = f"{logra_vinc}, {r.get('localidade')}, {clean_cep}, Brasil"

        geo = _ors_client.pelias_search(text=query, size=1)
        if geo and len(geo['features']) > 0:
            feat = geo['features'][0]
            c = feat['geometry']['coordinates']
            return {
                "lat": c[1], 
                "lon": c[0], 
                "endereco": f"{logra_vinc} ({clean_cep})",
                "cep": clean_cep
            }
    except: return None
    return None

# --- 3. INICIALIZAÇÃO ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro na API Key. Verifique os Secrets."); st.stop()

u_base = {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 4. INTERFACE SIDEBAR ---
with st.sidebar:
    st.header("🚚 Tecnolab Fleet")
    tipo_calc = st.selectbox("Estratégia:", ["Melhor Caminho (IA)", "Ordem da Lista"])
    
    st.subheader("📍 Destinos (Máx 5)")
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"Parada {i+1}", key=f"p_{i}", placeholder="00000-000")
        if c: ceps_raw.append(c)
    
    btn_calc = st.button("🚀 GERAR ROTA", use_container_width=True, type="primary")
    if st.button("🗑️ Limpar", use_container_width=True):
        st.session_state.res_v106 = None
        st.rerun()

# --- 5. LÓGICA DE CÁLCULO ---
if btn_calc and ceps_raw:
    with st.spinner("Otimizando..."):
        pontos = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pontos.append(res)
        
        if not pontos:
            st.error("Nenhum CEP válido encontrado.")
        else:
            # Coordenadas: [Base, P1, P2, P3, P4, P5, Base]
            coords = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pontos] + [[u_base['lon'], u_base['lat']]]
            
            try:
                otimizar = (tipo_calc == "Melhor Caminho (IA)")
                rota_geo = ors_client.directions(
                    coordinates=coords, 
                    profile='driving-car', 
                    format='geojson', 
                    optimize_waypoints=otimizar
                )

                # --- CAPTURA DA ORDEM OTIMIZADA ---
                # A API retorna waypoint_order para os pontos entre o primeiro e o último.
                if otimizar and 'waypoint_order' in rota_geo['metadata']['query']:
                    w_order = rota_geo['metadata']['query']['waypoint_order']
                    # w_order vem como [2, 0, 1...] referente aos pontos intermediários
                    ordem_final = [0] + [i + 1 for i in w_order] + [len(coords)-1]
                else:
                    ordem_final = list(range(len(coords)))

                # Organizar dados para exibição
                labels_all = [u_base['nome']] + [p['endereco'] for p in pontos] + [u_base['nome']]
                
                itinerario = []
                segmentos = rota_geo['features'][0]['properties']['segments']
                for idx, step_idx in enumerate(ordem_final[1:]):
                    seg = segmentos[idx]
                    itinerario.append({
                        "Seq": f"{idx+1}º",
                        "Destino": labels_all[step_idx],
                        "Distância": f"{round(seg['distance']/1000, 2)} km",
                        "Tempo": f"{round(seg['duration']/60, 1)} min"
                    })

                st.session_state.res_v106 = {
                    "tabela": itinerario,
                    "geometria": [[c[1], c[0]] for c in rota_geo['features'][0]['geometry']['coordinates']],
                    "pontos_mapa": pontos, # Para os marcadores azuis
                    "dist_total": round(rota_geo['features'][0]['properties']['summary']['distance']/1000, 2)
                }
            except Exception as e:
                st.error(f"Erro na API ORS: {e}")

# --- 6. RESULTADOS E MAPA ---
if "res_v106" in st.session_state and st.session_state.res_v106:
    res = st.session_state.res_v106
    st.subheader(f"Resumo da Rota: {res['dist_total']} km")
    
    col_tab, col_map = st.columns([1, 1.5])
    
    with col_tab:
        st.dataframe(pd.DataFrame(res['tabela']), use_container_width=True, hide_index=True)
        
    with col_map:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        
        # 1. Linha do Percurso
        folium.PolyLine(res['geometria'], color="#2E86C1", weight=5, opacity=0.8).add_to(m)
        
        # 2. Marcador Matriz (Verde)
        folium.Marker(
            [u_base['lat'], u_base['lon']], 
            tooltip="MATRIZ TECNOLAB", 
            icon=folium.Icon(color='green', icon='home')
        ).add_to(m)
        
        # 3. Marcadores de Destino (Azul com Tooltip fixo)
        for p in res['pontos_mapa']:
            folium.Marker(
                [p['lat'], p['lon']], 
                tooltip=p['endereco'], # Aparece ao passar o mouse
                popup=p['endereco'],  # Aparece ao clicar
                icon=folium.Icon(color='blue', icon='info-sign')
            ).add_to(m)
            
        st_folium(m, use_container_width=True, height=500)
