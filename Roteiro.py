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
st.set_page_config(page_title="Roteirizador Tecnolab V11.0", layout="wide", page_icon="🚚")

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
    # Explicação clara das opções
    tipo_calc = st.radio(
        "Escolha a lógica:",
        ["Ordem da Lista (Rígida)", "Melhor Caminho (Otimizado)"],
        help="A primeira segue sua digitação. A segunda reorganiza para economizar combustível."
    )
    
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"CEP Destino {i+1}", key=f"c_{i}")
        if c: ceps_raw.append(c)
    
    btn_calc = st.button("🚀 GERAR ROTEIRO", use_container_width=True, type="primary")

# --- 5. LÓGICA DE CÁLCULO ---
if btn_calc and ceps_raw:
    with st.spinner("Mapeando pontos..."):
        pontos_originais = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pontos_originais.append(res)
        
        if not pontos_originais:
            st.error("Nenhum CEP válido."); st.stop()

        try:
            # Montar coordenadas: Início + Pontos + Fim
            coords = [[u_base['lon'], u_base['lat']]]
            coords += [[p['lon'], p['lat']] for p in pontos_originais]
            coords += [[u_base['lon'], u_base['lat']]]

            # Chamar API
            otimizar = (tipo_calc == "Melhor Caminho (Otimizado)")
            rota_geo = ors_client.directions(
                coordinates=coords,
                profile='driving-car',
                format='geojson',
                optimize_waypoints=otimizar
            )

            # --- O SEGREDO DA SINCRONIA ---
            # Pegamos a ordem que a API usou de fato
            if otimizar and 'waypoint_order' in rota_geo['metadata']['query']:
                ordem_ia = rota_geo['metadata']['query']['waypoint_order']
                # Reorganizamos nossa lista de pontos para bater com o desenho do mapa
                pontos_finais = [pontos_originais[i] for i in ordem_ia]
            else:
                # Mantém a ordem exata da lista digitada
                pontos_finais = pontos_originais

            # Montar Itinerário para Tabela e Marcadores
            itinerario_completo = []
            segmentos = rota_geo['features'][0]['properties']['segments']
            
            # 1. Ponto Inicial
            itinerario_completo.append({
                "Seq": "Saída", "Destino": u_base['nome'], "Distancia": "-", "Tempo": "-",
                "lat": u_base['lat'], "lon": u_base['lon']
            })

            # 2. Pontos Intermediários (na ordem que a rota foi traçada)
            for i, p in enumerate(pontos_finais):
                itinerario_completo.append({
                    "Seq": f"{i+1}º",
                    "Destino": f"{p['endereco']} ({p['cep']})",
                    "Distancia": f"{round(segmentos[i]['distance']/1000, 2)} km",
                    "Tempo": f"{round(segmentos[i]['duration']/60, 1)} min",
                    "lat": p['lat'], "lon": p['lon']
                })

            # 3. Retorno
            itinerario_completo.append({
                "Seq": "Retorno", "Destino": u_base['nome'], 
                "Distancia": f"{round(segmentos[-1]['distance']/1000, 2)} km", 
                "Tempo": f"{round(segmentos[-1]['duration']/60, 1)} min",
                "lat": u_base['lat'], "lon": u_base['lon']
            })

            st.session_state.dados_rota = {
                "tabela": itinerario_completo,
                "geometria": [[c[1], c[0]] for c in rota_geo['features'][0]['geometry']['coordinates']],
                "dist_total": round(rota_geo['features'][0]['properties']['summary']['distance']/1000, 2)
            }
        except Exception as e:
            st.error(f"Erro no cálculo: {e}")

# --- 6. EXIBIÇÃO ---
if "dados_rota" in st.session_state:
    res = st.session_state.dados_rota
    
    col1, col2 = st.columns([1, 1.3])
    
    with col1:
        st.subheader("📋 Itinerário Detalhado")
        st.dataframe(pd.DataFrame(res['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        
        pdf_bytes = gerar_pdf(res['tabela'], res['dist_total'])
        st.download_button(label="📥 Baixar Itinerário (PDF)", data=pdf_bytes, file_name="rota_tecnolab.pdf", mime="application/pdf")

    with col2:
        st.subheader(f"🗺️ Mapa (Total: {res['dist_total']} km)")
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(res['geometria'], color="#2E86C1", weight=6, opacity=0.8).add_to(m)
        
        for item in res['tabela']:
            is_base = item['Seq'] in ['Saída', 'Retorno']
            # O número no pop-up e o tooltip agora batem exatamente com a ordem do traçado
            folium.Marker(
                location=[item['lat'], item['lon']],
                tooltip=f"Parada: {item['Seq']}",
                popup=folium.Popup(f"<b>Ordem:</b> {item['Seq']}<br><b>Local:</b> {item['Destino']}", max_width=250),
                icon=folium.Icon(color='green' if is_base else 'blue', icon='info-sign' if not is_base else 'home')
            ).add_to(m)
        
        st_folium(m, use_container_width=True, height=550)
