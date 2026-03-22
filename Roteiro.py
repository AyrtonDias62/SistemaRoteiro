import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import urllib.parse
import os

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Tecnolab Logística V16.7", layout="wide", page_icon="🧪")

# CSS para ajuste de topo e compactação da Sidebar
st.markdown("""
    <style>
        [data-testid="stSidebarNav"] {display: none;}
        section[data-testid="stSidebar"] .block-container {padding-top: 1.5rem !important;}
        .main .block-container {padding-top: 3.5rem !important;}
        [data-testid="stVerticalBlock"] {gap: 0.6rem;}
    </style>
""", unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def get_coords_cep(cep_raw, num_raw, _ors_key):
    try:
        cep = "".join(filter(str.isdigit, str(cep_raw))).strip()
        num = "".join(filter(str.isdigit, str(num_raw))).strip()
        if len(cep) != 8: return None
        v_res = requests.get(f"https://viacep.com.br/ws/{cep}/json/").json()
        if "erro" in v_res: return None
        rua, bairro, cidade, uf = v_res.get('logradouro', ''), v_res.get('bairro', ''), v_res.get('localidade', ''), v_res.get('uf', '')
        url = "https://api.openrouteservice.org/geocode/search"
        params = {
            'api_key': _ors_key, 'text': f"{cep}, {cidade}, {uf}, Brasil", 'size': 1,
            'boundary.circle.lat': -23.6912, 'boundary.circle.lon': -46.5594, 'boundary.circle.radius': 50
        }
        resp = requests.get(url, params=params).json()
        if not resp.get('features'):
            params['text'] = f"{rua}, {cidade}, {uf}, Brasil"
            resp = requests.get(url, params=params).json()
        if resp.get('features'):
            feat = resp['features'][0]
            if "coimbra" in feat['properties'].get('label', '').lower() and "columbia" in rua.lower():
                params['text'] = f"{cep}, Brasil"
                resp = requests.get(url, params=params).json()
            coords = resp['features'][0]['geometry']['coordinates']
            return {"lat": coords[1], "lon": coords[0], "endereco": f"{rua}, {num} - {bairro}", "cidade": cidade}
        return None
    except: return None

# --- 2. SETUP ---
ORS_KEY = st.secrets["ORS_KEY"]
ors_client = client.Client(key=ORS_KEY)
u_base = {"endereco": "Unidade Matriz SBC", "lat": -23.6930, "lon": -46.5560}

# --- 3. SIDEBAR ---
with st.sidebar:
    img_path = "furgao_tecnolab.png"
    if os.path.exists(img_path):
        st.image(img_path, width=180) 
    
    st.subheader("Gestão de Rotas")
    
    if 'reset_id' not in st.session_state: st.session_state.reset_id = 0

    modo = st.radio("Método:", ["Ordem Digitada", "Otimizar Caminho"], 
                    key=f"m_{st.session_state.reset_id}", horizontal=True)
    
    st.divider()
    
    entradas = []
    for i in range(5):
        c1, c2 = st.columns([1.5, 0.8])
        with c1:
            ce = st.text_input(f"CEP {i+1}", key=f"c_{i}_{st.session_state.reset_id}", label_visibility="collapsed", placeholder=f"CEP {i+1}")
        with c2:
            nu = st.text_input(f"Nº", key=f"n_{i}_{st.session_state.reset_id}", label_visibility="collapsed", placeholder="Nº")
        if ce: entradas.append({"cep": ce, "num": nu})

    st.divider()
    
    col_g, col_l = st.columns(2)
    with col_g:
        btn_gerar = st.button("🚀 GERAR", use_container_width=True, type="primary")
    with col_l:
        if st.button("🗑️ LIMPAR", use_container_width=True):
            if "res_v167" in st.session_state: del st.session_state.res_v167
            st.session_state.reset_id += 1
            st.rerun()

# --- 4. LOGÍSTICA ---
if btn_gerar and entradas:
    pts_gps = []
    for item in entradas:
        res = get_coords_cep(item['cep'], item['num'], ORS_KEY)
        if res: pts_gps.append(res)
        else: st.error(f"CEP {item['cep']} não encontrado.")

    if pts_gps:
        if "Otimizar" in modo:
            pend, atu, ord_list = pts_gps.copy(), u_base, []
            while pend:
                locs = [[atu['lon'], atu['lat']]] + [[p['lon'], p['lat']] for p in pend]
                dm = ors_client.distance_matrix(locations=locs, profile='driving-car', metrics=['distance'])
                idx = dm['distances'][0][1:].index(min(dm['distances'][0][1:]))
                proximo = pend.pop(idx); ord_list.append(proximo); atu = proximo
        else: ord_list = pts_gps

        rota_f = [u_base] + ord_list + [u_base]
        tab, lin, km, t_min = [], [], 0, 0
        tab.append({"Ordem": "SAÍDA", "Local": u_base['endereco'], "Dist.": "-", "Tempo": "-", "lat": u_base['lat'], "lon": u_base['lon']})

        for i in range(len(rota_f) - 1):
            A, B = rota_f[i], rota_f[i+1]
            try:
                dr = ors_client.directions(coordinates=[[A['lon'], A['lat']], [B['lon'], B['lat']]], profile='driving-car', format='geojson')
                s = dr['features'][0]['properties']['summary']
                d_k, d_m = round(s['distance']/1000, 2), round(s['duration']/60)
                km += d_k; t_min += d_m
                lin.extend([[c[1], c[0]] for c in dr['features'][0]['geometry']['coordinates']])
                lbl = "RETORNO" if i == len(rota_f)-2 else f"{i+1}ª PARADA"
                tab.append({"Ordem": lbl, "Local": B['endereco'], "Dist.": f"{d_k} km", "Tempo": f"{d_m} min", "lat": B['lat'], "lon": B['lon']})
            except: pass
        st.session_state.res_v167 = {"t": tab, "l": lin, "k": round(km, 2), "m": t_min}

# --- 5. EXIBIÇÃO ---
if "res_v167" in st.session_state:
    d = st.session_state.res_v167
    st.header(f"📊 Resumo: {d['k']} km | {d['m']} min")
    
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.dataframe(pd.DataFrame(d['t']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        link = f"https://www.google.com/maps/dir/{'/'.join([f'{p['lat']},{p['lon']}' for p in d['t']])}"
        st.link_button("🟢 WHATSAPP / GPS", f"https://api.whatsapp.com/send?text={urllib.parse.quote(link)}", use_container_width=True)
    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        if d['l']: folium.PolyLine(d['l'], color="red", weight=5).add_to(m)
        for p in d['t']:
            # POP-UP RESTAURADO: Ordem em negrito como primeiro valor
            texto_popup = f"<b>{p['Ordem']}</b><br>{p['Local']}"
            folium.Marker(
                [p['lat'], p['lon']], 
                popup=folium.Popup(texto_popup, max_width=300), 
                tooltip=p['Ordem'], # Aparece ao passar o mouse
                icon=folium.Icon(color="green" if p['Ordem'] in ["SAÍDA", "RETORNO"] else "blue")
            ).add_to(m)
        st_folium(m, use_container_width=True, height=480)
