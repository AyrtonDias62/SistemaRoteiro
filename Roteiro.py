import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import urllib.parse

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Tecnolab Logística V16.2", layout="wide", page_icon="🧪")

@st.cache_data(show_spinner=False)
def get_coords_cep(cep_raw, num_raw, _ors_key):
    try:
        cep = "".join(filter(str.isdigit, str(cep_raw))).strip()
        num = "".join(filter(str.isdigit, str(num_raw))).strip()
        if len(cep) != 8: return None
        
        # 1. ViaCEP: Garante que o texto da tabela esteja sempre certo
        v_res = requests.get(f"https://viacep.com.br/ws/{cep}/json/").json()
        if "erro" in v_res: return None
        
        rua_oficial = v_res.get('logradouro', '')
        bairro = v_res.get('bairro', '')
        cidade = v_res.get('localidade', '')

        # 2. Busca Geográfica (ORS): Focamos apenas no CEP para evitar erro de número não mapeado
        url = "https://api.openrouteservice.org/geocode/search"
        params = {
            'api_key': _ors_key,
            'text': f"{cep}, Brasil", # Busca por CEP é infalível e evita erro fonético Columbia/Coimbra
            'size': 1,
            'boundary.circle.lat': -23.6912,
            'boundary.circle.lon': -46.5594,
            'boundary.circle.radius': 40
        }
        resp = requests.get(url, params=params).json()

        if resp.get('features'):
            coords = resp['features'][0]['geometry']['coordinates']
            return {
                "lat": coords[1], "lon": coords[0], 
                "endereco": f"{rua_oficial}, {num} - {bairro}", 
                "cidade": cidade
            }
        return None
    except: return None

# --- 2. SETUP ---
try:
    ORS_KEY = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=ORS_KEY)
except:
    st.error("Erro na ORS_KEY."); st.stop()

u_base = {"endereco": "Unidade Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 3. SIDEBAR (CONTROLE DE RESET) ---
with st.sidebar:
    st.title("🚚 Roteirizador")
    if 'reset_id' not in st.session_state: st.session_state.reset_id = 0

    modo = st.radio("Método:", ["Ordem Digitada", "Otimizar Caminho"], key=f"m_{st.session_state.reset_id}")
    st.divider()
    
    entradas = []
    for i in range(5):
        c1, c2 = st.columns([2, 1])
        with c1: ce = st.text_input(f"CEP {i+1}", key=f"c_{i}_{st.session_state.reset_id}")
        with c2: nu = st.text_input(f"Nº", key=f"n_{i}_{st.session_state.reset_id}")
        if ce: entradas.append({"cep": ce, "num": nu})

    st.divider()
    col_g, col_l = st.columns(2)
    with col_g: btn_gerar = st.button("🚀 GERAR", use_container_width=True, type="primary")
    with col_l:
        if st.button("🗑️ LIMPAR", use_container_width=True):
            if "res_v162" in st.session_state: del st.session_state.res_v162
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
            dr = ors_client.directions(coordinates=[[A['lon'], A['lat']], [B['lon'], B['lat']]], profile='driving-car', format='geojson')
            s = dr['features'][0]['properties']['summary']
            d_k, d_m = round(s['distance']/1000, 2), round(s['duration']/60)
            km += d_k; t_min += d_m
            lin.extend([[c[1], c[0]] for c in dr['features'][0]['geometry']['coordinates']])
            lbl = "RETORNO" if i == len(rota_f)-2 else f"{i+1}ª PARADA"
            tab.append({"Ordem": lbl, "Local": B['endereco'], "Dist.": f"{d_k} km", "Tempo": f"{d_m} min", "lat": B['lat'], "lon": B['lon']})

        st.session_state.res_v162 = {"t": tab, "l": lin, "k": round(km, 2), "m": t_min}

# --- 5. EXIBIÇÃO ---
if "res_v162" in st.session_state:
    d = st.session_state.res_v162
    st.header(f"📊 {d['k']} km | {d['m']} min")
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.dataframe(pd.DataFrame(d['t']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        link = f"https://www.google.com/maps/dir/{'/'.join([f'{p['lat']},{p['lon']}' for p in d['t']])}"
        st.link_button("🟢 WHATSAPP", f"https://api.whatsapp.com/send?text={urllib.parse.quote(link)}", use_container_width=True)
    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=13)
        folium.PolyLine(d['l'], color="red", weight=5).add_to(m)
        for p in d['t']:
            folium.Marker([p['lat'], p['lon']], popup=f"<b>{p['Ordem']}</b><br>{p['Local']}", icon=folium.Icon(color="green" if "Matriz" in p['Local'] else "blue")).add_to(m)
        st_folium(m, use_container_width=True, height=500)
