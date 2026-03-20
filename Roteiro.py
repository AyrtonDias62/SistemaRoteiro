import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from fpdf import FPDF

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V13.0", layout="wide", page_icon="🚚")

# --- 2. FUNÇÕES AUXILIARES ---
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

def gerar_pdf(dados, dist_total):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(190, 10, "ITINERARIO TECNOLAB - CONTROLE DE KM", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(190, 10, f"Distancia Total do Percurso: {dist_total} km", ln=True, align="C")
    pdf.ln(5)
    pdf.set_font("Arial", "B", 9)
    pdf.cell(20, 10, "Seq", 1); pdf.cell(110, 10, "Local", 1); pdf.cell(30, 10, "Km Trecho", 1); pdf.cell(30, 10, "Tempo", 1, 1)
    pdf.set_font("Arial", "", 8)
    for i in dados:
        try: dest = i['Destino'].encode('latin-1', 'replace').decode('latin-1')
        except: dest = "Endereco"
        pdf.cell(20, 8, str(i['Seq']), 1)
        pdf.cell(110, 8, dest[:60], 1)
        pdf.cell(30, 8, str(i['Distancia']), 1)
        pdf.cell(30, 8, str(i['Tempo']), 1, 1)
    return pdf.output(dest='S').encode('latin-1', 'ignore')

# --- 3. SETUP API ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro: Verifique a ORS_KEY nos Secrets."); st.stop()

u_base = {"endereco": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594, "cep": "Matriz"}

# --- 4. INTERFACE ---
with st.sidebar:
    st.header("🚚 Painel Tecnolab")
    modo = st.radio("Estratégia de Rota:", ["Ordem da Lista", "Otimizar para Menor Caminho"])
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"Ponto {i+1}", key=f"c_v13_{i}", placeholder="Digite o CEP")
        if c: ceps_raw.append(c)
    btn_calc = st.button("🚀 GERAR ROTA PROFISSIONAL", use_container_width=True, type="primary")

# --- 5. LÓGICA DE PROCESSAMENTO V13.0 (IA + ISOLAMENTO) ---
if btn_calc and ceps_raw:
    with st.spinner("IA calculando a melhor logística..."):
        pts_gps = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pts_gps.append(res)
        
        if not pts_gps:
            st.error("Nenhum CEP válido encontrado."); st.stop()

        try:
            # FASE 1: DESCOBRIR A ORDEM ÓTIMA (IA TSP)
            if modo == "Otimizar para Menor Caminho":
                coords_ia = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps] + [[u_base['lon'], u_base['lat']]]
                res_ia = ors_client.directions(
                    coordinates=coords_ia,
                    profile='driving-car',
                    optimize_waypoints=True
                )
                ordem_ia = res_ia['metadata']['query']['waypoint_order']
                pts_ordenados = [pts_gps[i] for i in ordem_ia]
            else:
                pts_ordenados = pts_gps

            # FASE 2: CÁLCULO INDIVIDUAL DE CADA TRECHO (ISOLAMENTO TOTAL)
            itinerario = []
            geometria_total = []
            km_total = 0
            percurso = [u_base] + pts_ordenados + [u_base]
            
            # Linha de Saída
            itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Distancia": "0.0 km", "Tempo": "0 min", "lat": u_base['lat'], "lon": u_base['lon']})

            for i in range(len(percurso) - 1):
                origem, destino = percurso[i], percurso[i+1]
                
                # Chamada isolada para este trecho específico
                trecho = ors_client.directions(
                    coordinates=[[origem['lon'], origem['lat']], [destino['lon'], destino['lat']]],
                    profile='driving-car', format='geojson'
                )
                
                d = trecho['features'][0]['properties']['summary']
                d_km = round(d['distance'] / 1000, 2)
                t_min = round(d['duration'] / 60, 1)
                km_total += d_km
                
                geometria_total.extend([[c[1], c[0]] for c in trecho['features'][0]['geometry']['coordinates']])
                
                label = "Retorno" if i == len(percurso) - 2 else f"{i+1}ª Parada"
                itinerario.append({
                    "Seq": label,
                    "Destino": f"{destino['endereco']} ({destino.get('cep', '')})",
                    "Distancia": f"{d_km} km",
                    "Tempo": f"{t_min} min",
                    "lat": destino['lat'], "lon": destino['lon']
                })

            st.session_state.v13 = {"tabela": itinerario, "mapa": geometria_total, "total": round(km_total, 2)}
        except Exception as e:
            st.error(f"Erro na roteirização: {e}")

# --- 6. EXIBIÇÃO ---
if "v13" in st.session_state:
    r = st.session_state.v13
    st.subheader(f"📊 Relatório Final: {r['total']} km")
    
    col_t, col_m = st.columns([1, 1.3])
    with col_t:
        st.dataframe(pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        pdf_data = gerar_pdf(r['tabela'], r['total'])
        st.download_button("📥 Baixar PDF", data=pdf_data, file_name="itinerario_tecnolab.pdf", mime="application/pdf")

    with col_m:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(r['mapa'], color="#2E86C1", weight=6, opacity=0.8).add_to(m)
        for i in r['tabela']:
            is_base = i['Seq'] in ['Saída', 'Retorno']
            folium.Marker(
                [i['lat'], i['lon']], 
                tooltip=i['Seq'], 
                icon=folium.Icon(color='green' if is_base else 'blue', icon='home' if is_base else 'info-sign'),
                popup=f"<b>{i['Seq']}</b><br>{i['Destino']}"
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
