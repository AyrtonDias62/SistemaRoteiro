import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from fpdf import FPDF

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V11.5", layout="wide", page_icon="🚚")

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
    pdf.cell(190, 10, f"Distancia Total: {dist_total} km", ln=True, align="C")
    pdf.ln(5)
    pdf.set_font("Arial", "B", 9)
    pdf.cell(20, 10, "Seq", 1); pdf.cell(110, 10, "Local", 1); pdf.cell(30, 10, "Km", 1); pdf.cell(30, 10, "Min", 1, 1)
    pdf.set_font("Arial", "", 8)
    for i in dados:
        try:
            dest = i['Destino'].encode('latin-1', 'replace').decode('latin-1')
        except:
            dest = "Endereco com caracteres especiais"
        pdf.cell(20, 8, str(i['Seq']), 1)
        pdf.cell(110, 8, dest[:60], 1)
        pdf.cell(30, 8, str(i['Distancia']), 1)
        pdf.cell(30, 8, str(i['Tempo']), 1, 1)
    return pdf.output(dest='S').encode('latin-1', 'ignore')

# --- 3. INICIALIZAÇÃO ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro na ORS_KEY."); st.stop()

u_base = {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 4. INTERFACE ---
with st.sidebar:
    st.header("🚚 Painel de Frota")
    modo = st.radio("Configuração de Percurso:", ["Ordem da Lista", "Menor Caminho (IA)"])
    st.divider()
    ceps_input = []
    for i in range(5):
        c = st.text_input(f"CEP {i+1}", key=f"cep_v115_{i}")
        if c: ceps_input.append(c)
    btn_gerar = st.button("🚀 GERAR ROTA", use_container_width=True, type="primary")

# --- 5. LÓGICA DE PROCESSAMENTO ---
if btn_gerar and ceps_input:
    with st.spinner("Sincronizando logradouros..."):
        pts_encontrados = []
        for c in ceps_input:
            res = get_coords_cep(c, ors_client)
            if res: pts_encontrados.append(res)
        
        if not pts_encontrados:
            st.error("Nenhum CEP válido."); st.stop()

        try:
            # 1. Montar coordenadas iniciais [Base, Pontos..., Base]
            coords_full = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_encontrados] + [[u_base['lon'], u_base['lat']]]
            
            otimizar = (modo == "Menor Caminho (IA)")
            
            # 2. Chamada Principal
            res_api = ors_client.directions(
                coordinates=coords_full,
                profile='driving-car',
                format='geojson',
                optimize_waypoints=otimizar
            )

            # 3. IDENTIFICAÇÃO DA ORDEM CORRETA (Coração da correção)
            if otimizar and 'waypoint_order' in res_api['metadata']['query']:
                ordem_ia = res_api['metadata']['query']['waypoint_order']
                # Reorganiza os pontos baseado na ordem que a IA decidiu
                pts_finais = [pts_encontrados[i] for i in ordem_ia]
            else:
                pts_finais = pts_encontrados

            # 4. MONTAGEM DO ITINERÁRIO (Mapeamento 1:1)
            # Os 'segments' da API seguem a ordem do percurso desenhado
            itinerario = []
            segs = res_api['features'][0]['properties']['segments']
            
            # Início
            itinerario.append({"Seq": "Saída", "Destino": u_base['nome'], "Distancia": "0.0 km", "Tempo": "0 min", "lat": u_base['lat'], "lon": u_base['lon']})
            
            # Trechos até cada ponto
            for idx, ponto in enumerate(pts_finais):
                itinerario.append({
                    "Seq": f"{idx+1}º",
                    "Destino": f"{ponto['endereco']} ({ponto['cep']})",
                    "Distancia": f"{round(segs[idx]['distance']/1000, 2)} km",
                    "Tempo": f"{round(segs[idx]['duration']/60, 1)} min",
                    "lat": ponto['lat'], "lon": ponto['lon']
                })
            
            # Retorno (Último segmento calculado pela API)
            itinerario.append({
                "Seq": "Retorno", 
                "Destino": u_base['nome'], 
                "Distancia": f"{round(segs[-1]['distance']/1000, 2)} km", 
                "Tempo": f"{round(segs[-1]['duration']/60, 1)} min",
                "lat": u_base['lat'], "lon": u_base['lon']
            })

            st.session_state.result_v115 = {
                "tabela": itinerario,
                "geometria": [[c[1], c[0]] for c in res_api['features'][0]['geometry']['coordinates']],
                "dist_total": round(res_api['features'][0]['properties']['summary']['distance']/1000, 2)
            }
        except Exception as e:
            st.error(f"Erro no cálculo: {e}")

# --- 6. EXIBIÇÃO ---
if "result_v115" in st.session_state:
    res = st.session_state.result_v115
    st.success(f"Itinerário Final: {res['dist_total']} km percorridos.")
    
    c_tab, c_map = st.columns([1, 1.2])
    with c_tab:
        st.dataframe(pd.DataFrame(res['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        pdf_f = gerar_pdf(res['tabela'], res['dist_total'])
        st.download_button("📥 Baixar Itinerário (PDF)", data=pdf_f, file_name="itinerario_tecnolab.pdf", mime="application/pdf")

    with c_map:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(res['geometria'], color="#2E86C1", weight=6).add_to(m)
        for i in res['tabela']:
            is_m = i['Seq'] in ['Saída', 'Retorno']
            folium.Marker(
                [i['lat'], i['lon']], 
                tooltip=i['Seq'], 
                icon=folium.Icon(color='green' if is_m else 'blue', icon='home' if is_m else 'info-sign'),
                popup=f"<b>{i['Seq']}</b><br>{i['Destino']}"
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
