import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from fpdf import FPDF
import io

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V11.1", layout="wide", page_icon="🚚")

# --- 2. FUNÇÕES AUXILIARES ---
@st.cache_data(show_spinner=False)
def get_coords_cep(cep, _ors_client):
    try:
        clean_cep = str(cep).replace('-', '').replace(' ', '').strip()
        r = requests.get(f"https://viacep.com.br/ws/{clean_cep}/json/").json()
        if "erro" in r:
            query = f"{clean_cep}, Brasil"
            logra = f"CEP {clean_cep}"
        else:
            logra = f"{r.get('logradouro')}, {r.get('bairro')}"
            query = f"{logra}, {r.get('localidade')}, {clean_cep}, Brasil"

        geo = _ors_client.pelias_search(text=query, size=1)
        if geo and len(geo['features']) > 0:
            c = geo['features'][0]['geometry']['coordinates']
            return {"lat": c[1], "lon": c[0], "endereco": logra, "cep": clean_cep}
    except: return None
    return None

def gerar_pdf(dados, dist_total):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, "TECNOLAB - RELATORIO DE ROTA", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.cell(190, 10, f"Distancia Total: {dist_total} km", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(20, 10, "Seq", 1); pdf.cell(110, 10, "Ponto", 1); pdf.cell(30, 10, "KM", 1); pdf.cell(30, 10, "Tempo", 1, 1)
    pdf.set_font("Arial", "", 9)
    for item in dados:
        pdf.cell(20, 8, str(item['Seq']), 1)
        pdf.cell(110, 8, str(item['Destino'])[:55], 1)
        pdf.cell(30, 8, str(item['Distancia']), 1)
        pdf.cell(30, 8, str(item['Tempo']), 1, 1)
    return pdf.output(dest='S').encode('latin-1', 'ignore')

# --- 3. INICIALIZAÇÃO ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Configure a ORS_KEY nos Secrets."); st.stop()

u_base = {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("🚚 Gestão de Rota")
    tipo_calc = st.radio(
        "Modo de Roteirização:",
        ["Manter Ordem Digitação", "Otimizar Menor Caminho"],
        help="O modo Otimizar reorganiza os pontos para reduzir a quilometragem total."
    )
    
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"Ponto {i+1}", key=f"c_{i}", placeholder="00000-000")
        if c: ceps_raw.append(c)
    
    btn_calc = st.button("🚀 GERAR ROTA", use_container_width=True, type="primary")

# --- 5. LÓGICA DE CÁLCULO ---
if btn_calc and ceps_raw:
    with st.spinner("Processando..."):
        pontos_gps = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pontos_gps.append(res)
        
        if not pontos_gps:
            st.error("Nenhum CEP válido encontrado."); st.stop()

        try:
            # Construir coordenadas para a API
            # Ordem: [MATRIZ, P1, P2, P3, P4, P5, MATRIZ]
            coords_chamada = [[u_base['lon'], u_base['lat']]]
            coords_chamada += [[p['lon'], p['lat']] for p in pontos_gps]
            coords_chamada += [[u_base['lon'], u_base['lat']]]

            otimizar_bool = (tipo_calc == "Otimizar Menor Caminho")
            
            # Chamada principal da API
            res_api = ors_client.directions(
                coordinates=coords_chamada,
                profile='driving-car',
                format='geojson',
                optimize_waypoints=otimizar_bool
            )

            # EXTRAÇÃO DA ORDEM FINAL
            # Se otimizado, a API retorna 'waypoint_order' (ex: [1, 0, 2])
            if otimizar_bool and 'waypoint_order' in res_api['metadata']['query']:
                ordem_indices = res_api['metadata']['query']['waypoint_order']
                # Reorganizar os objetos de pontos baseados na decisão da IA
                pontos_finais = [pontos_gps[i] for i in ordem_indices]
            else:
                # Mantém a ordem da lista
                pontos_finais = pontos_gps

            # Construção do Itinerário para Tabela e Mapa
            itinerario = []
            segmentos = res_api['features'][0]['properties']['segments']
            
            # 1. Ponto de Partida
            itinerario.append({
                "Seq": "Saída", "Destino": u_base['nome'], "Distancia": "-", "Tempo": "-",
                "lat": u_base['lat'], "lon": u_base['lon']
            })

            # 2. Paradas (respeitando a ordem do traçado azul no mapa)
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
                "Seq": "Retorno", "Destino": u_base['nome'],
                "Distancia": f"{round(segmentos[-1]['distance']/1000, 2)} km",
                "Tempo": f"{round(segmentos[-1]['duration']/60, 1)} min",
                "lat": u_base['lat'], "lon": u_base['lon']
            })

            st.session_state.resultado = {
                "tabela": itinerario,
                "geometria": [[c[1], c[0]] for c in res_api['features'][0]['geometry']['coordinates']],
                "dist_total": round(res_api['features'][0]['properties']['summary']['distance']/1000, 2)
            }
        except Exception as e:
            st.error(f"Erro ao calcular: {e}")

# --- 6. EXIBIÇÃO ---
if "resultado" in st.session_state:
    res = st.session_state.resultado
    
    st.success(f"Cálculo concluído: {res['dist_total']} km total.")
    
    col_tab, col_map = st.columns([1, 1.3])
    
    with col_tab:
        st.markdown("### 📋 Itinerário")
        df_display = pd.DataFrame(res['tabela']).drop(columns=['lat', 'lon'])
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        
        pdf_bytes = gerar_pdf(res['tabela'], res['dist_total'])
        st.download_button("📥 Baixar Itinerário em PDF", data=pdf_bytes, file_name="itinerario.pdf", mime="application/pdf")

    with col_map:
        st.markdown("### 🗺️ Mapa do Percurso")
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        
        # Desenhar a linha azul da rota
        folium.PolyLine(res['geometria'], color="#2E86C1", weight=6, opacity=0.8).add_to(m)
        
        # Marcadores sincronizados com a tabela
        for item in res['resultado' if False else 'tabela']:
            base = item['Seq'] in ['Saída', 'Retorno']
            folium.Marker(
                [item['lat'], item['lon']],
                tooltip=f"Parada: {item['Seq']}",
                popup=f"<b>{item['Seq']}</b><br>{item['Destino']}",
                icon=folium.Icon(color='green' if base else 'blue', icon='home' if base else 'info-sign')
            ).add_to(m)
            
        st_folium(m, use_container_width=True, height=500)
