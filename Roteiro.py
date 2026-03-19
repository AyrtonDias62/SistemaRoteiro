import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import base64
from PIL import Image
import io

# --- 1. CONFIGURAÇÃO E ESTILO (FORÇAR VISIBILIDADE) ---
st.set_page_config(page_title="Roteirizador Tecnolab V10.4", layout="wide", page_icon="🚚")

st.markdown("""
    <style>
    [data-testid="stSidebar"] { min-width: 220px !important; max-width: 260px !important; }
    .main-title { color: #2E86C1; font-size: 24px; font-weight: bold; margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
    div[data-testid="stTextInput"] { margin-bottom: -15px; }
    .stDataFrame { border: 1px solid #e6e9ef; border-radius: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. FUNÇÕES CORE ---
@st.cache_data(show_spinner=False)
def get_coords_cep(cep, _client_ors):
    try:
        clean_cep = str(cep).replace('-','').replace(' ', '').strip()
        
        # 1. Tentativa Direta no ORS (Mais preciso para coordenadas)
        # Buscamos pelo CEP + País para evitar ambiguidades
        geo = _client_ors.pelias_search(text=f"{clean_cep}, Brasil", size=1)
        
        if geo and len(geo['features']) > 0:
            feat = geo['features'][0]
            c = feat['geometry']['coordinates']
            # Extrai o nome da rua/bairro retornado pelo próprio ORS para conferência
            label = feat['properties'].get('label', 'Endereço encontrado')
            return {"lat": c[1], "lon": c[0], "endereco": label, "cep": cep}
            
        # 2. Fallback: Se o ORS falhar, usa ViaCEP + ORS detalhado
        r = requests.get(f"https://viacep.com.br/ws/{clean_cep}/json/").json()
        if "erro" not in r:
            logra = r.get('logradouro')
            bairro = r.get('bairro')
            cidade = r.get('localidade')
            # Busca combinada para maior precisão
            busca_full = f"{logra}, {bairro}, {cidade}, SP, Brasil"
            geo_fallback = _client_ors.pelias_search(text=busca_full, size=1)
            
            if geo_fallback and len(geo_fallback['features']) > 0:
                c = geo_fallback['features'][0]['geometry']['coordinates']
                return {"lat": c[1], "lon": c[0], "endereco": f"{logra}, {bairro}", "cep": cep}
    except Exception as e:
        print(f"Erro no geocoding: {e}")
        return None

# --- 3. INICIALIZAÇÃO ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Chave API ORS não encontrada nos Secrets."); st.stop()

u_base = {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 4. TÍTULO SEMPRE VISÍVEL ---
st.markdown('<p class="main-title">🚚 Roteirizador Tecnolab - Gestão de Frota</p>', unsafe_allow_html=True)

# --- 5. SIDEBAR (ENTRADA DE DADOS) ---
with st.sidebar:
    st.subheader("⚙️ Configuração")
    tipo_calc = st.radio("Tipo de Rota:", ["Ordem da Lista", "Melhor Caminho (IA)"])
    
    st.divider()
    st.subheader("📍 Destinos")
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"P{i}", key=f"c104_{i}", label_visibility="collapsed", placeholder=f"Digite o CEP {i+1}")
        if c: ceps_raw.append(c)
    
    btn_calc = st.button("🚀 CALCULAR ROTA", use_container_width=True, type="primary")
    if st.button("🗑️ Limpar Tudo", use_container_width=True):
        st.session_state.res_v104 = None
        st.rerun()

# --- 6. LÓGICA DE CÁLCULO ---
if btn_calc and ceps_raw:
    with st.spinner("Mapeando endereços..."):
        pontos_encontrados = []
        for c in ceps_raw:
            res_cep = get_coords_cep(c, ors_client)
            if res_cep: pontos_encontrados.append(res_cep)
        
        if not pontos_encontrados:
            st.error("Nenhum CEP válido foi encontrado.")
        else:
            coords = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pontos_encontrados] + [[u_base['lon'], u_base['lat']]]
            
            try:
                otimizar = (tipo_calc == "Melhor Caminho (IA)")
                rota_geo = ors_client.directions(coordinates=coords, profile='driving-car', format='geojson', optimize_waypoints=otimizar)
                
                # Definir Ordem Final
                if otimizar and 'waypoint_order' in rota_geo['metadata']['query']:
                    ordem_indices = [0] + [i + 1 for i in rota_geo['metadata']['query']['waypoint_order']] + [len(coords)-1]
                else:
                    ordem_indices = list(range(len(coords)))

                # Nomes para a tabela
                labels_puros = [f"Saída: {u_base['nome']}"] + [f"{p['endereco']} ({p['cep']})" for p in pontos_encontrados] + [f"Retorno: {u_base['nome']}"]
                labels_finais = [labels_puros[i] for i in ordem_indices]
                
                # Montar Tabela
                dados_tabela = []
                # Linha de Saída Inicial
                dados_tabela.append({"Seq": "Início", "Ponto de Parada": labels_finais[0], "Distância": "-", "Tempo": "-"})
                
                segmentos = rota_geo['features'][0]['properties']['segments']
                for i, s in enumerate(segmentos):
                    dados_tabela.append({
                        "Seq": f"{i+1}º",
                        "Ponto de Parada": labels_finais[i+1],
                        "Distância": f"{round(s['distance']/1000, 2)} km",
                        "Tempo": f"{round(s['duration']/60, 1)} min"
                    })

                # Preparar Marcadores do Mapa
                marcadores = [{"lat": u_base['lat'], "lon": u_base['lon'], "info": "SAÍDA/RETORNO", "cor": "green"}]
                if otimizar:
                    for seq, idx in enumerate(rota_geo['metadata']['query']['waypoint_order']):
                        p = pontos_encontrados[idx]
                        marcadores.append({"lat": p['lat'], "lon": p['lon'], "info": f"{seq+1}ª Parada: {p['endereco']}", "cor": "blue"})
                else:
                    for seq, p in enumerate(pontos_encontrados):
                        marcadores.append({"lat": p['lat'], "lon": p['lon'], "info": f"{seq+1}ª Parada: {p['endereco']}", "cor": "blue"})

                st.session_state.res_v104 = {
                    "tabela": dados_tabela,
                    "polilinha": [[p[1], p[0]] for p in rota_geo['features'][0]['geometry']['coordinates']],
                    "marcadores": marcadores
                }
            except Exception as e:
                st.error(f"Erro ao calcular rota: {e}")

# --- 7. EXIBIÇÃO DOS RESULTADOS ---
if "res_v104" in st.session_state and st.session_state.res_v104:
    r = st.session_state.res_v104
    
    col_quadro, col_mapa = st.columns([0.9, 1.1])
    
    with col_quadro:
        st.markdown("##### 📋 Itinerário Detalhado")
        st.dataframe(pd.DataFrame(r['tabela']), use_container_width=True, hide_index=True)
        
        # Resumo rápido embaixo da tabela
        km_total = sum([float(x.replace(' km', '')) for x in [d['Distância'] for d in r['tabela']] if 'km' in x])
        st.info(f"**Resumo:** Distância total de aproximadamente **{round(km_total, 2)} km**.")

    with col_mapa:
        st.markdown("##### 🗺️ Visualização do Percurso")
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12, tiles="cartodbpositron")
        
        for p in r['marcadores']:
            folium.Marker([p['lat'], p['lon']], icon=folium.Icon(color=p['cor'], icon='info-sign'), tooltip=p['info']).add_to(m)
        
        folium.PolyLine(r['polilinha'], color="#2E86C1", weight=5, opacity=0.8).add_to(m)
        st_folium(m, use_container_width=True, height=600)
