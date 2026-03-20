import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from fpdf import FPDF

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V11.9", layout="wide", page_icon="🚚")

# --- 2. FUNÇÕES ---
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

# --- 3. SETUP ---
try:
    ors_key = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=ors_key)
except:
    st.error("Erro: ORS_KEY não configurada nos Secrets."); st.stop()

# Base com os mesmos campos dos pontos para evitar erro de chave
u_base = {"endereco": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594, "cep": "Matriz"}

# --- 4. INTERFACE ---
with st.sidebar:
    st.header("🚚 Painel Tecnolab")
    modo = st.radio("Logística:", ["Ordem da Lista", "Menor Caminho (IA)"])
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"Ponto {i+1}", key=f"c_v119_{i}")
        if c: ceps_raw.append(c)
    btn_calc = st.button("🚀 CALCULAR ROTA", use_container_width=True, type="primary")

# --- 5. LÓGICA DE PROCESSAMENTO ---
if btn_calc and ceps_raw:
    with st.spinner("Calculando percurso..."):
        pts_gps = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pts_gps.append(res)
        
        if not pts_gps:
            st.error("Nenhum CEP válido encontrado."); st.stop()

        try:
            # 1. Definir a ordem
            if modo == "Menor Caminho (IA)":
                coords_otimizar = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps] + [[u_base['lon'], u_base['lat']]]
                res_ia = ors_client.directions(coordinates=coords_otimizar, profile='driving-car', optimize_waypoints=True)
                ordem = res_ia['metadata']['query']['waypoint_order']
                pts_ordenados = [pts_gps[i] for i in ordem]
            else:
                pts_ordenados = pts_gps

            # 2. Construção por pernas (Garante distâncias reais de cada trecho)
            itinerario = []
            geometria_completa = []
            dist_acumulada = 0
            
            # Adicionar a Saída manualmente
            itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Distancia": "0.0 km", "Tempo": "0 min", "lat": u_base['lat'], "lon": u_base['lon']})
            
            # Criar lista completa: [BASE, P1, P2..., BASE]
            percurso = [u_base] + pts_ordenados + [u_base]
            
            for i in range(len(percurso) - 1):
                p_ini = percurso[i]
                p_fim = percurso[i+1]
                
                # Chamada de trecho individual
                trecho = ors_client.directions(
                    coordinates=[[p_ini['lon'], p_ini['lat']], [p_fim['lon'], p_fim['lat']]],
                    profile='driving-car', format='geojson'
                )
                
                res_trecho = trecho['features'][0]['properties']['summary']
                d_km = round(res_trecho['distance'] / 1000, 2)
                t_min = round(res_trecho['duration'] / 60, 1)
                dist_acumulada += d_km
                
                # Geometria para o mapa
                geometria_completa.extend([[c[1], c[0]] for c in trecho['features'][0]['geometry']['coordinates']])
                
                # Identificar se é uma parada ou o retorno
                label = "Retorno" if i == len(percurso) - 2 else f"{i+1}º"
                
                itinerario.append({
                    "Seq": label,
                    "Destino": f"{p_fim['endereco']} ({p_fim['cep']})",
                    "Distancia": f"{d_km} km",
                    "Tempo": f"{t_min} min",
                    "lat": p_fim['lat'], "lon": p_fim['lon']
                })

            st.session_state.v119 = {
                "tabela": itinerario,
                "mapa": geometria_completa,
                "total": round(dist_acumulada, 2)
            }
        except Exception as e:
            st.error(f"Erro no processamento técnico: {e}")

# --- 6. EXIBIÇÃO ---
if "v119" in st.session_state:
    r = st.session_state.v119
    st.subheader(f"Resumo da Rota: {r['total']} km")
    
    c1, c2 = st.columns([1, 1.3])
    with c1:
        st.dataframe(pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        pdf = gerar_pdf(r['tabela'], r['total'])
        st.download_button("📥 Baixar Itinerário (PDF)", data=pdf, file_name="itinerario.pdf", mime="application/pdf")

    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(r['mapa'], color="#2E86C1", weight=5).add_to(m)
        for i in r['tabela']:
            is_b = i['Seq'] in ['Saída', 'Retorno']
            folium.Marker(
                [i['lat'], i['lon']], 
                tooltip=i['Seq'], 
                icon=folium.Icon(color='green' if is_b else 'blue', icon='home' if is_b else 'info-sign')
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
