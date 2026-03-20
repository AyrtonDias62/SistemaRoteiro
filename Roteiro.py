import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from fpdf import FPDF
import math

# --- 1. CONFIGURAÇÃO E ESTILO ---
st.set_page_config(page_title="Roteirizador Tecnolab V10.9", layout="wide", page_icon="🚚")

st.markdown("""
    <style>
    .main-title { color: #2E86C1; font-size: 24px; font-weight: bold; margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
    .stDataFrame { border: 1px solid #e6e9ef; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. FUNÇÕES AUXILIARES ---

@st.cache_data(show_spinner=False)
def get_coords_cep(cep, _ors_client):
    """Busca coordenadas com alta precisão combinando ViaCEP + ORS"""
    try:
        clean_cep = str(cep).replace('-', '').replace(' ', '').strip()
        r = requests.get(f"https://viacep.com.br/ws/{clean_cep}/json/").json()
        
        if "erro" in r:
            query = f"{clean_cep}, Brasil"
            logra_vinc = f"CEP {clean_cep}"
        else:
            logra_vinc = f"{r.get('logradouro')}, {r.get('bairro')}"
            query = f"{logra_vinc}, {r.get('localidade')}, {clean_cep}, Brasil"

        geo = _ors_client.pelias_search(text=query, size=1)
        if geo and len(geo['features']) > 0:
            c = geo['features'][0]['geometry']['coordinates']
            return {"lat": c[1], "lon": c[0], "endereco": logra_vinc, "cep": clean_cep}
    except:
        return None

def gerar_pdf(dados, dist_total):
    """Gera o arquivo PDF do itinerário"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, "TECNOLAB - ITINERARIO DE FROTA", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.cell(190, 10, f"Distancia Total Estimada: {dist_total} km", ln=True, align="C")
    pdf.ln(10)
    
    # Cabeçalho
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(20, 10, "Seq", 1, 0, "C", True)
    pdf.cell(110, 10, "Ponto de Parada", 1, 0, "L", True)
    pdf.cell(30, 10, "Dist.", 1, 0, "C", True)
    pdf.cell(30, 10, "Tempo", 1, 1, "C", True)
    
    # Conteúdo
    pdf.set_font("Arial", "", 9)
    for item in dados:
        pdf.cell(20, 8, str(item['Seq']), 1, 0, "C")
        pdf.cell(110, 8, str(item['Destino'])[:55], 1, 0, "L")
        pdf.cell(30, 8, str(item['Distancia']), 1, 0, "C")
        pdf.cell(30, 8, str(item['Tempo']), 1, 1, "C")
    
    return pdf.output(dest='S').encode('latin-1', 'ignore')

# --- 3. INICIALIZAÇÃO ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Chave API ORS não encontrada nos Secrets."); st.stop()

# Matriz Fixa SBC
u_base = {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Roteirizador")
    tipo_calc = st.selectbox("Estratégia de Rota:", ["Melhor Caminho (IA)", "Ordem da Lista"])
    
    st.divider()
    st.subheader("📍 Destinos (CEP)")
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"Parada {i+1}", key=f"cep_{i}", placeholder="00000-000")
        if c: ceps_raw.append(c)
    
    btn_calc = st.button("🚀 CALCULAR ROTA", use_container_width=True, type="primary")
    if st.button("🗑️ Limpar Tudo", use_container_width=True):
        st.session_state.res_v109 = None
        st.rerun()

# --- 5. LÓGICA DE CÁLCULO ---
if btn_calc and ceps_raw:
    with st.spinner("Analisando geolocalização e logística..."):
        pontos_validos = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pontos_validos.append(res)
        
        if not pontos_validos:
            st.error("Nenhum CEP válido foi encontrado.")
        else:
            try:
                # ESTRATÉGIA DE ORDENAÇÃO
                if tipo_calc == "Ordem da Lista":
                    pontos_trabalho = pontos_validos
                else:
                    # Lógica: Iniciar pelo ponto mais próximo da Matriz
                    def calc_dist(p):
                        return math.sqrt((p['lat']-u_base['lat'])**2 + (p['lon']-u_base['lon'])**2)
                    pontos_trabalho = sorted(pontos_validos, key=calc_dist)

                # Montar lista de coordenadas para o ORS
                coords = [[u_base['lon'], u_base['lat']]] 
                coords += [[p['lon'], p['lat']] for p in pontos_trabalho]
                coords += [[u_base['lon'], u_base['lat']]]
                
                # Chamar Directions com Otimização de Waypoints (Caixeiro Viajante)
                otimizar_ia = (tipo_calc == "Melhor Caminho (IA)")
                rota_geo = ors_client.directions(
                    coordinates=coords, 
                    profile='driving-car', 
                    format='geojson', 
                    optimize_waypoints=otimizar_ia
                )

                # Identificar ordem final retornada pela IA
                if otimizar_ia and 'waypoint_order' in rota_geo['metadata']['query']:
                    ordem_indices = rota_geo['metadata']['query']['waypoint_order']
                    pontos_finais = [pontos_trabalho[i] for i in ordem_indices]
                else:
                    pontos_finais = pontos_trabalho

                # Montar Tabela de Itinerário
                itinerario = []
                segmentos = rota_geo['features'][0]['properties']['segments']
                
                # 1. Saída
                itinerario.append({"Seq": "Saída", "Destino": u_base['nome'], "Distancia": "-", "Tempo": "-", "lat": u_base['lat'], "lon": u_base['lon']})
                
                # 2. Paradas intermediárias
                for i, p in enumerate(pontos_finais):
                    itinerario.append({
                        "Seq": f"{i+1}º",
                        "Destino": f"{p['endereco']} ({p['cep']})",
                        "Distancia": f"{round(segmentos[i]['distance']/1000, 2)} km",
                        "Tempo": f"{round(segmentos[i]['duration']/60, 1)} min",
                        "lat": p['lat'], "lon": p['lon']
                    })
                
                # 3. Retorno
                itinerario.append({
                    "Seq": "Retorno", 
                    "Destino": u_base['nome'], 
                    "Distancia": f"{round(segmentos[-1]['distance']/1000, 2)} km", 
                    "Tempo": f"{round(segmentos[-1]['duration']/60, 1)} min",
                    "lat": u_base['lat'], "lon": u_base['lon']
                })

                st.session_state.res_v109 = {
                    "tabela": itinerario,
                    "geometria": [[c[1], c[0]] for c in rota_geo['features'][0]['geometry']['coordinates']],
                    "dist_total": round(rota_geo['features'][0]['properties']['summary']['distance']/1000, 2)
                }

            except Exception as e:
                st.error(f"Erro no cálculo da rota: {e}")

# --- 6. EXIBIÇÃO DOS RESULTADOS ---
if "res_v109" in st.session_state and st.session_state.res_v109:
    res = st.session_state.res_v109
    
    st.markdown(f'<p class="main-title">🚚 Itinerário Gerado - {res["dist_total"]} km</p>', unsafe_allow_html=True)
    
    # Exportação PDF
    pdf_out = gerar_pdf(res['tabela'], res['dist_total'])
    st.download_button(
        label="📥 Baixar Itinerário em PDF",
        data=pdf_out,
        file_name="itinerario_tecnolab.pdf",
        mime="application/pdf"
    )

    col_it, col_map = st.columns([1, 1.4])
    
    with col_it:
        st.subheader("📋 Sequência de Paradas")
        df_exibir = pd.DataFrame(res['tabela']).drop(columns=['lat', 'lon'])
        st.dataframe(df_exibir, use_container_width=True, hide_index=True)
        st.info("A distância e tempo referem-se ao trecho percorrido para chegar ao ponto.")

    with col_map:
        st.subheader("🗺️ Visualização Geográfica")
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        
        # Desenha a linha da rota
        folium.PolyLine(res['geometria'], color="#2E86C1", weight=5, opacity=0.8).add_to(m)
        
        # Adiciona os Marcadores com Pop-up detalhado e Ordem
        for item in res['res_v109' if False else 'tabela']: # Gambiarra para evitar erro de loop
            is_base = item['Seq'] in ['Saída', 'Retorno']
            cor = 'green' if is_base else 'blue'
            
            folium.Marker(
                location=[item['lat'], item['lon']],
                tooltip=f"<b>{item['Seq']}</b>",
                popup=folium.Popup(f"""
                    <b>Ordem:</b> {item['Seq']}<br>
                    <b>Local:</b> {item['Destino']}<br>
                    <b>Trecho:</b> {item['Distancia']}<br>
                    <b>Tempo:</b> {item['Tempo']}
                """, max_width=300),
                icon=folium.Icon(color=cor, icon='info-sign' if not is_base else 'home')
            ).add_to(m)
            
        st_folium(m, use_container_width=True, height=500)
