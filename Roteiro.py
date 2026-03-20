import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from fpdf import FPDF

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V11.7", layout="wide", page_icon="🚚")

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
        try:
            dest = i['Destino'].encode('latin-1', 'replace').decode('latin-1')
        except: dest = "Endereco"
        pdf.cell(20, 8, str(i['Seq']), 1)
        pdf.cell(110, 8, dest[:60], 1)
        pdf.cell(30, 8, str(i['Distancia']), 1)
        pdf.cell(30, 8, str(i['Tempo']), 1, 1)
    return pdf.output(dest='S').encode('latin-1', 'ignore')

# --- 3. SETUP ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro na ORS_KEY."); st.stop()

u_base = {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 4. INTERFACE ---
with st.sidebar:
    st.header("🚚 Painel Tecnolab")
    modo = st.radio("Logística:", ["Ordem da Lista", "Menor Caminho (IA)"])
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"Ponto {i+1}", key=f"c_v117_{i}")
        if c: ceps_raw.append(c)
    btn_calc = st.button("🚀 CALCULAR ROTA", use_container_width=True, type="primary")

# --- 5. LÓGICA DE PROCESSAMENTO ---
if btn_calc and ceps_raw:
    with st.spinner("Sincronizando trechos..."):
        pts_gps = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pts_gps.append(res)
        
        if not pts_gps:
            st.error("Nenhum CEP válido."); st.stop()

        try:
            # 1. Coordenadas iniciais
            coords_full = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps] + [[u_base['lon'], u_base['lat']]]
            otimizar = (modo == "Menor Caminho (IA)")
            
            res_api = ors_client.directions(
                coordinates=coords_full,
                profile='driving-car',
                format='geojson',
                optimize_waypoints=otimizar
            )

            # 2. SEGREDO: Descobrir qual ponto é qual após a otimização
            # A API retorna waypoint_order: [1, 0] significa que o Ponto 2 foi visitado antes do Ponto 1.
            if otimizar and 'waypoint_order' in res_api['metadata']['query']:
                ordem_real = res_api['metadata']['query']['waypoint_order']
                pts_ordenados = [pts_gps[i] for i in ordem_real]
            else:
                pts_ordenados = pts_gps

            # 3. Montar Itinerário usando a ordem que REALMENTE está no mapa
            itinerario = []
            segs = res_api['features'][0]['properties']['segments']
            
            # Saída
            itinerario.append({"Seq": "Saída", "Destino": u_base['nome'], "Distancia": "0.0 km", "Tempo": "0 min", "lat": u_base['lat'], "lon": u_base['lon']})
            
            # Paradas intermediárias (cada segs[i] leva ao pts_ordenados[i])
            for i, p in enumerate(pts_ordenados):
                d_km = round(segs[i]['distance'] / 1000, 2)
                t_min = round(segs[i]['duration'] / 60, 1)
                itinerario.append({
                    "Seq": f"{i+1}º",
                    "Destino": f"{p['endereco']} ({p['cep']})",
                    "Distancia": f"{d_km} km",
                    "Tempo": f"{t_min} min",
                    "lat": p['lat'], "lon": p['lon']
                })
            
            # Retorno (Último segmento da API: do último ponto de volta à Matriz)
            d_ret = round(segs[-1]['distance'] / 1000, 2)
            t_ret = round(segs[-1]['duration'] / 60, 1)
            itinerario.append({
                "Seq": "Retorno", 
                "Destino": u_base['nome'], 
                "Distancia": f"{d_ret} km", 
                "Tempo": f"{t_ret} min",
                "lat": u_base['lat'], "lon": u_base['lon']
            })

            st.session_state.v117 = {
                "tabela": itinerario,
                "mapa": [[c[1], c[0]] for c in res_api['features'][0]['geometry']['coordinates']],
                "total": round(res_api['features'][0]['properties']['summary']['distance']/1000, 2)
            }
        except Exception as e:
            st.error(f"Erro no cálculo: {e}")

# --- 6. EXIBIÇÃO ---
if "v117" in st.session_state:
    r = st.session_state.v117
    st.subheader(f"Resumo da Rota: {r['total']} km")
    
    col1, col2 = st.columns([1, 1.3])
    with col1:
        st.dataframe(pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        pdf = gerar_pdf(r['tabela'], r['total'])
        st.download_button("📥 Baixar PDF", data=pdf, file_name="itinerario.pdf", mime="application/pdf")

    with col2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(r['mapa'], color="blue", weight=5, opacity=0.7).add_to(m)
        for i in r['tabela']:
            base = i['Seq'] in ['Saída', 'Retorno']
            folium.Marker(
                [i['lat'], i['lon']], 
                tooltip=f"{i['Seq']}", 
                popup=f"<b>{i['Seq']}</b>: {i['Destino']}",
                icon=folium.Icon(color='green' if base else 'blue', icon='home' if base else 'info-sign')
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
