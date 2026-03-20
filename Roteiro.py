import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
from fpdf import FPDF

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V11.4", layout="wide", page_icon="🚚")

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
        # Usamos .encode('latin-1', 'replace').decode('latin-1') para evitar erros de caracteres
        destino_limpo = i['Destino'].encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(20, 8, str(i['Seq']), 1)
        pdf.cell(110, 8, destino_limpo[:60], 1)
        pdf.cell(30, 8, str(i['Distancia']), 1)
        pdf.cell(30, 8, str(i['Tempo']), 1, 1)
    return pdf.output(dest='S').encode('latin-1', 'ignore')

# --- 3. INICIALIZAÇÃO API ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro: Verifique a ORS_KEY nos Secrets do Streamlit."); st.stop()

u_base = {"nome": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 4. INTERFACE (Criação das variáveis que causaram o NameError) ---
with st.sidebar:
    st.header("🚚 Configuração")
    modo = st.radio("Logística:", ["Ordem Digitada", "Otimizar Caminho (IA)"])
    st.divider()
    
    ceps = []
    for i in range(5):
        c = st.text_input(f"CEP Destino {i+1}", key=f"c_{i}", placeholder="00000-000")
        if c: ceps.append(c)
    
    btn = st.button("🚀 GERAR ROTA", use_container_width=True, type="primary")

# --- 5. LÓGICA DE PROCESSAMENTO (Só executa APÓS o botão ser clicado) ---
if btn and ceps:
    with st.spinner("Sincronizando distâncias reais..."):
        pts_gps = []
        for c in ceps:
            res = get_coords_cep(c, ors_client)
            if res: pts_gps.append(res)
        
        if not pts_gps:
            st.error("Nenhum CEP válido encontrado."); st.stop()

        try:
            # Coordenadas: Matriz -> Pontos -> Matriz
            coords_chamada = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps] + [[u_base['lon'], u_base['lat']]]
            
            otimizar_ia = (modo == "Otimizar Caminho (IA)")
            res_api = ors_client.directions(
                coordinates=coords_chamada, 
                profile='driving-car', 
                format='geojson', 
                optimize_waypoints=otimizar_ia
            )

            # Sincronização de Ordem (O segredo para bater os quadros)
            if otimizar_ia and 'waypoint_order' in res_api['metadata']['query']:
                ordem_ia = res_api['metadata']['query']['waypoint_order']
                pts_finais = [pts_gps[i] for i in ordem_ia]
            else:
                pts_finais = pts_gps

            # Montagem do Itinerário
            itinerario = []
            segs = res_api['features'][0]['properties']['segments']
            
            # Saída
            itinerario.append({
                "Seq": "Saída", "Destino": u_base['nome'], "Distancia": "0.0 km", "Tempo": "0 min",
                "lat": u_base['lat'], "lon": u_base['lon']
            })
            
            # Pontos
            for i, p in enumerate(pts_finais):
                dist_km = round(segs[i]['distance'] / 1000, 2)
                tempo_min = round(segs[i]['duration'] / 60, 1)
                itinerario.append({
                    "Seq": f"{i+1}º",
                    "Destino": f"{p['endereco']} ({p['cep']})",
                    "Distancia": f"{dist_km} km",
                    "Tempo": f"{tempo_min} min",
                    "lat": p['lat'], "lon": p['lon']
                })
            
            # Retorno
            dist_ret = round(segs[-1]['distance'] / 1000, 2)
            tempo_ret = round(segs[-1]['duration'] / 60, 1)
            itinerario.append({
                "Seq": "Retorno", "Destino": u_base['nome'], "Distancia": f"{dist_ret} km", "Tempo": f"{tempo_ret} min",
                "lat": u_base['lat'], "lon": u_base['lon']
            })

            st.session_state.v114 = {
                "tabela": itinerario,
                "mapa": [[c[1], c[0]] for c in res_api['features'][0]['geometry']['coordinates']],
                "total": round(res_api['features'][0]['properties']['summary']['distance']/1000, 2)
            }
        except Exception as e:
            st.error(f"Erro no processamento: {e}")

# --- 6. EXIBIÇÃO DOS RESULTADOS ---
if "v114" in st.session_state:
    r = st.session_state.v114
    st.subheader(f"Total da Rota: {r['total']} km")
    
    col1, col2 = st.columns([1, 1.2])
    with col1:
        df_display = pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon'])
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        
        pdf_data = gerar_pdf(r['tabela'], r['total'])
        st.download_button("📥 Baixar Itinerário (PDF)", data=pdf_data, file_name="itinerario.pdf", mime="application/pdf")

    with col2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(r['mapa'], color="#2E86C1", weight=6).add_to(m)
        for i in r['tabela']:
            is_b = i['Seq'] in ['Saída', 'Retorno']
            folium.Marker(
                [i['lat'], i['lon']], 
                tooltip=i['Seq'], 
                icon=folium.Icon(color='green' if is_b else 'blue', icon='home' if is_b else 'info-sign'),
                popup=f"<b>{i['Seq']}</b><br>{i['Destino']}"
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
