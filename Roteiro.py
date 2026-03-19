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
st.set_page_config(page_title="Roteirizador Tecnolab V10.7", layout="wide", page_icon="🚚")

# --- 2. FUNÇÕES AUXILIARES ---
@st.cache_data(show_spinner=False)
def get_coords_cep(cep, _ors_client):
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
    except: return None
    return None

def gerar_pdf(dados, dist_total):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, "Itinerário de Frota - Tecnolab", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.cell(190, 10, f"Distância Total Estimada: {dist_total} km", ln=True, align="C")
    pdf.ln(10)
    
    # Cabeçalho da Tabela
    pdf.set_fill_color(200, 220, 255)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(15, 10, "Seq", 1, 0, "C", True)
    pdf.cell(115, 10, "Ponto de Parada", 1, 0, "L", True)
    pdf.cell(30, 10, "Dist.", 1, 0, "C", True)
    pdf.cell(30, 10, "Tempo", 1, 1, "C", True)
    
    # Linhas
    pdf.set_font("Arial", "", 9)
    for item in dados:
        # Truncar endereço se for muito longo
        end = item['Destino'][:60]
        pdf.cell(15, 8, item['Seq'], 1, 0, "C")
        pdf.cell(115, 8, end, 1, 0, "L")
        pdf.cell(30, 8, item['Distância'], 1, 0, "C")
        pdf.cell(30, 8, item['Tempo'], 1, 1, "C")
        
    return pdf.output(dest='S').encode('latin-1')

# --- 3. INICIALIZAÇÃO API ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro na API Key ORS."); st.stop()

u_base = {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("🚚 Tecnolab Fleet")
    tipo_calc = st.selectbox("Estratégia:", ["Melhor Caminho (IA)", "Ordem da Lista"])
    
    st.subheader("📍 Destinos (Máx 5)")
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"Parada {i+1}", key=f"p_{i}", placeholder="CEP")
        if c: ceps_raw.append(c)
    
    btn_calc = st.button("🚀 GERAR ROTA", use_container_width=True, type="primary")

# --- 5. LÓGICA DE CÁLCULO ---
if btn_calc and ceps_raw:
    with st.spinner("Calculando melhor rota..."):
        pontos_validos = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pontos_validos.append(res)
        
        if not pontos_validos:
            st.error("Nenhum CEP encontrado.")
        else:
            coords = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pontos_validos] + [[u_base['lon'], u_base['lat']]]
            
            try:
                otimizar = (tipo_calc == "Melhor Caminho (IA)")
                rota_geo = ors_client.directions(coordinates=coords, profile='driving-car', format='geojson', optimize_waypoints=otimizar)

                # Definir ordem final dos objetos de pontos
                if otimizar and 'waypoint_order' in rota_geo['metadata']['query']:
                    w_order = rota_geo['metadata']['query']['waypoint_order']
                    # O waypoint_order da API diz a ordem dos pontos intermediários
                    pontos_ordenados = [pontos_validos[i] for i in w_order]
                else:
                    pontos_ordenados = pontos_validos

                # Montar Itinerário
                itinerario = []
                segmentos = rota_geo['features'][0]['properties']['segments']
                
                # Início
                itinerario.append({"Seq": "Saída", "Destino": u_base['nome'], "Distância": "-", "Tempo": "-", "lat": u_base['lat'], "lon": u_base['lon']})
                
                for i, p in enumerate(pontos_ordenados):
                    seg = segmentos[i]
                    itinerario.append({
                        "Seq": f"{i+1}º",
                        "Destino": p['endereco'],
                        "Distância": f"{round(seg['distance']/1000, 2)} km",
                        "Tempo": f"{round(seg['duration']/60, 1)} min",
                        "lat": p['lat'], "lon": p['lon']
                    })
                
                # Retorno
                seg_retorno = segmentos[-1]
                itinerario.append({"Seq": "Retorno", "Destino": u_base['nome'], "Distância": f"{round(seg_retorno['distance']/1000, 2)} km", "Tempo": f"{round(seg_retorno['duration']/60, 1)} min", "lat": u_base['lat'], "lon": u_base['lon']})

                st.session_state.res_v107 = {
                    "tabela": itinerario,
                    "geometria": [[c[1], c[0]] for c in rota_geo['features'][0]['geometry']['coordinates']],
                    "dist_total": round(rota_geo['features'][0]['properties']['summary']['distance']/1000, 2)
                }
            except Exception as e:
                st.error(f"Erro: {e}")

# --- 6. EXIBIÇÃO ---
if "res_v107" in st.session_state:
    res = st.session_state.res_v107
    st.subheader(f"Resumo: {res['dist_total']} km")
    
    # Botão de PDF
    pdf_bytes = gerar_pdf(res['tabela'], res['dist_total'])
    st.download_button(
        label="📥 Baixar Itinerário em PDF", 
        data=pdf_bytes, 
        file_name="rota_tecnolab.pdf", 
        mime="application/pdf"
    )
    
    c1, c2 = st.columns([1, 1.4])
    with c1:
        st.dataframe(pd.DataFrame(res['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
    
    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(res['geometria'], color="#2E86C1", weight=5, opacity=0.8).add_to(m)
        
        for item in res['tabela']:
            cor = 'green' if item['Seq'] in ['Saída', 'Retorno'] else 'blue'
            icone = 'play' if item['Seq'] == 'Saída' else 'stop' if item['Seq'] == 'Retorno' else 'info-sign'
            
            folium.Marker(
                [item['lat'], item['lon']],
                tooltip=f"<b>{item['Seq']}</b>: {item['Destino']}",
                popup=folium.Popup(f"<b>Ordem:</b> {item['Seq']}<br><b>Local:</b> {item['Destino']}<br><b>Dist. Trecho:</b> {item['Distância']}", max_width=300),
                icon=folium.Icon(color=cor, icon=icone)
            ).add_to(m)
            
        st_folium(m, use_container_width=True, height=500)
