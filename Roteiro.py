import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium

# --- 1. CONFIGURAÇÃO E ESTILO ---
st.set_page_config(page_title="Roteirizador Tecnolab V10.5", layout="wide", page_icon="🚚")

st.markdown("""
    <style>
    [data-testid="stSidebar"] { min-width: 250px !important; }
    .main-title { color: #2E86C1; font-size: 24px; font-weight: bold; margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
    .stDataFrame { border: 1px solid #e6e9ef; border-radius: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. FUNÇÕES CORE ---
@st.cache_data(show_spinner=False)
def get_coords_cep(cep, _ors_client):
    """Busca coordenadas com precisão usando CEP + Geocodificação ORS"""
    try:
        clean_cep = str(cep).replace('-', '').replace(' ', '').strip()
        # 1. Busca via ViaCEP para pegar o nome da rua (ajuda na precisão do Pelias)
        r = requests.get(f"https://viacep.com.br/ws/{clean_cep}/json/").json()
        
        if "erro" in r:
            # Fallback: Tenta buscar o CEP direto no ORS se o ViaCEP falhar
            query = f"{clean_cep}, Brasil"
        else:
            # Combinação ultra-precisa: Rua, Cidade, CEP, Brasil
            query = f"{r.get('logradouro')}, {r.get('localidade')}, {clean_cep}, Brasil"

        # 2. Geocodificação via ORS (Pelias)
        geo = _ors_client.pelias_search(text=query, size=1)
        
        if geo and len(geo['features']) > 0:
            feat = geo['features'][0]
            c = feat['geometry']['coordinates']
            # Retorna o endereço formatado que o motor encontrou para conferência
            return {
                "lat": c[1], 
                "lon": c[0], 
                "endereco": feat['properties'].get('label', r.get('logradouro', 'Endereço')), 
                "cep": clean_cep
            }
    except Exception as e:
        st.error(f"Erro ao localizar CEP {cep}: {e}")
    return None

# --- 3. INICIALIZAÇÃO ---
try:
    # Substitua pelo seu segredo ou string da chave
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except Exception as e:
    st.error("Chave API ORS não encontrada ou inválida."); st.stop()

# Matriz Tecnolab SBC
u_base = {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 4. TÍTULO ---
st.markdown('<p class="main-title">🚚 Roteirizador Tecnolab - Gestão de Frota V10.5</p>', unsafe_allow_html=True)

# --- 5. SIDEBAR ---
with st.sidebar:
    st.subheader("⚙️ Configuração")
    tipo_calc = st.radio("Estratégia de Rota:", ["Ordem da Lista", "Melhor Caminho (Otimizado IA)"])
    
    st.divider()
    st.subheader("📍 Destinos")
    ceps_raw = []
    # Aumentei para 8 campos, sinta-se à vontade para ajustar
    for i in range(8):
        c = st.text_input(f"P{i+1}", key=f"cep_in_{i}", placeholder="Digite o CEP")
        if c: ceps_raw.append(c)
    
    btn_calc = st.button("🚀 CALCULAR ROTA", use_container_width=True, type="primary")
    if st.button("🗑️ Limpar Tudo", use_container_width=True):
        st.session_state.res_v105 = None
        st.rerun()

# --- 6. LÓGICA DE CÁLCULO (VERSÃO BLINDADA) ---
if btn_calc and ceps_raw:
    with st.spinner("Geocodificando e otimizando percurso..."):
        pontos_encontrados = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pontos_encontrados.append(res)
        
        if len(pontos_encontrados) < 1:
            st.warning("Insira pelo menos um CEP válido.")
        else:
            # Monta lista de coordenadas: Base -> Pontos -> Base
            coords = [[u_base['lon'], u_base['lat']]] 
            coords += [[p['lon'], p['lat']] for p in pontos_encontrados]
            coords += [[u_base['lon'], u_base['lat']]]
            
            try:
                otimizar = (tipo_calc == "Melhor Caminho (Otimizado IA)")
                
                # Chamada da API ORS
                rota_geo = ors_client.directions(
                    coordinates=coords,
                    profile='driving-car',
                    format='geojson',
                    optimize_waypoints=otimizar
                )
                
                # --- TRATAMENTO DA ORDEM DOS WAYPOINTS ---
                # O ORS retorna a ordem otimizada em metadata -> query -> waypoint_order
                # Ex: se temos Base(0), P1(1), P2(2), P3(3), Base(4) e a ordem vem [1, 0, 2]
                # Significa que o primeiro ponto a visitar é o P2 (index 1 + 1), depois P1, etc.
                
                ordem_indices = [0] # Sempre começa na base
                
                if otimizar:
                    # Captura segura da ordem otimizada
                    query_meta = rota_geo.get('metadata', {}).get('query', {})
                    way_order = query_meta.get('waypoint_order', [])
                    
                    if way_order:
                        # Os índices no waypoint_order referem-se aos pontos INTERMEDIÁRIOS (excluindo início e fim)
                        ordem_indices += [i + 1 for i in way_order]
                    else:
                        # Fallback se a API não retornou ordem (ex: apenas 1 ponto)
                        ordem_indices += list(range(1, len(coords) - 1))
                else:
                    # Ordem sequencial da lista
                    ordem_indices += list(range(1, len(coords) - 1))
                
                ordem_indices.append(len(coords) - 1) # Sempre termina na base
                
                # --- MONTAGEM DA TABELA E LABELS ---
                labels_puros = [u_base['nome']] + [f"{p['endereco']} ({p['cep']})" for p in pontos_encontrados] + [u_base['nome']]
                labels_ordenados = [labels_puros[i] for i in ordem_indices]
                
                dados_tabela = []
                segmentos = rota_geo['features'][0]['properties']['segments']
                
                # Linha inicial
                dados_tabela.append({"Ordem": "Início", "Local": labels_ordenados[0], "Dist. Parcial": "-", "Tempo Est." : "-"})
                
                for i, seg in enumerate(segmentos):
                    dados_tabela.append({
                        "Ordem": f"{i+1}º",
                        "Local": labels_ordenados[i+1],
                        "Dist. Parcial": f"{round(seg['distance']/1000, 2)} km",
                        "Tempo Est.": f"{round(seg['duration']/60, 1)} min"
                    })

                # Marcadores para o Mapa
                marcadores = []
                marcadores.append({"pos": [u_base['lat'], u_base['lon']], "txt": "MATRIZ", "cor": "red"})
                for idx, p in enumerate(pontos_encontrados):
                    marcadores.append({"pos": [p['lat'], p['lon']], "txt": f"Ponto: {p['endereco']}", "cor": "blue"})

                st.session_state.res_v105 = {
                    "tabela": dados_tabela,
                    "geometria": [[c[1], c[0]] for c in rota_geo['features'][0]['geometry']['coordinates']],
                    "marcadores": marcadores,
                    "dist_total": round(rota_geo['features'][0]['properties']['summary']['distance']/1000, 2)
                }

            except Exception as e:
                st.error(f"Erro no cálculo da rota: {e}")

# --- 7. EXIBIÇÃO ---
if "res_v105" in st.session_state and st.session_state.res_v105:
    res = st.session_state.res_v105
    
    c1, c2 = st.columns([1, 1.2])
    
    with c1:
        st.success(f"✅ Rota calculada: **{res['dist_total']} km** no total.")
        st.markdown("### 📋 Itinerário")
        st.dataframe(pd.DataFrame(res['tabela']), use_container_width=True, hide_index=True)
        
    with c2:
        st.markdown("### 🗺️ Mapa do Percurso")
        # Centraliza o mapa na matriz
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        
        # Desenha a linha da rota
        folium.PolyLine(res['geometria'], color="#2E86C1", weight=6, opacity=0.7).add_to(m)
        
        # Adiciona marcadores
        for mkr in res['marcadores']:
            folium.Marker(mkr['pos'], popup=mkr['txt'], icon=folium.Icon(color=mkr['cor'])).add_to(m)
            
        st_folium(m, use_container_width=True, height=500)
