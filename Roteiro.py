import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import urllib.parse

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Tecnolab V15.9 Estável", layout="wide", page_icon="🧪")

@st.cache_data(show_spinner=False)
def get_coords_cep(cep_raw, num_raw, _ors_key):
    try:
        cep = "".join(filter(str.isdigit, str(cep_raw))).strip()
        num = "".join(filter(str.isdigit, str(num_raw))).strip()
        if len(cep) != 8: return None
        
        # 1. ViaCEP: Nossa 'Fonte da Verdade' para o texto
        v_res = requests.get(f"https://viacep.com.br/ws/{cep}/json/").json()
        if "erro" in v_res: return None
        logradouro_oficial = v_res.get('logradouro', '')

        # 2. Busca Geográfica Estruturada (Anti-Coimbra)
        url = "https://api.openrouteservice.org/geocode/search"
        params = {
            'api_key': _ors_key,
            'text': f"{cep}, {num}, Brasil",
            'size': 1,
            'boundary.circle.lat': -23.6912,
            'boundary.circle.lon': -46.5594,
            'boundary.circle.radius': 40
        }
        resp = requests.get(url, params=params).json()
        
        # Validação Crítica: Se o mapa retornar Coimbra e o CEP for Columbia, ignoramos e buscamos só o CEP
        if resp.get('features'):
            label_mapa = resp['features'][0]['properties'].get('label', '').lower()
            if "coimbra" in label_mapa and "columbia" in logradouro_oficial.lower():
                # Força busca puramente pelo código postal (CEP) para precisão máxima
                params['text'] = f"{cep}, Brasil"
                resp = requests.get(url, params=params).json()

        if resp.get('features'):
            coords = resp['features'][0]['geometry']['coordinates']
            return {
                "lat": coords[1], "lon": coords[0], 
                "endereco": f"{logradouro_oficial}, {num} - {v_res.get('bairro')}", 
                "cidade": v_res.get('localidade')
            }
        return None
    except: return None

# --- 2. SETUP ---
ORS_KEY = st.secrets["ORS_KEY"]
ors_client = client.Client(key=ORS_KEY)
u_base = {"endereco": "Unidade Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 3. SIDEBAR (RESET TOTAL) ---
with st.sidebar:
    st.title("🚚 Roteirizador")
    
    # Gerenciamento de estado para os campos de entrada
    if 'reset_trigger' not in st.session_state:
        st.session_state.reset_trigger = 0

    modo = st.radio("Método:", ["Ordem Digitada", "Otimizar Caminho"], key=f"modo_{st.session_state.reset_trigger}")
    st.divider()
    
    inputs_validados = []
    for i in range(5):
        c1, c2 = st.columns([2, 1])
        # Aumentamos o valor da key a cada reset para forçar o Streamlit a redesenhar do zero
        with c1: ce = st.text_input(f"CEP {i+1}", key=f"cep_{i}_{st.session_state.reset_trigger}")
        with c2: nu = st.text_input(f"Nº {i+1}", key=f"num_{i}_{st.session_state.reset_trigger}")
        if ce: inputs_validados.append({"cep": ce, "num": nu})

    st.divider()
    col_g, col_l = st.columns(2)
    with col_g:
        btn_gerar = st.button("🚀 GERAR", use_container_width=True, type="primary")
    with col_l:
        if st.button("🗑️ LIMPAR", use_container_width=True):
            # Limpa resultados e incrementa o trigger para mudar as chaves dos inputs
            if "v159" in st.session_state: del st.session_state.v159
            st.session_state.reset_trigger += 1
            st.rerun()

# --- 4. LOGÍSTICA ---
if btn_gerar and inputs_validados:
    pts_gps = []
    for item in inputs_validados:
        res = get_coords_cep(item['cep'], item['num'], ORS_KEY)
        if res: pts_gps.append(res)
        else: st.error(f"CEP {item['cep']} não localizado.")

    if pts_gps:
        if "Otimizar" in modo:
            pendentes, atual, ordenados = pts_gps.copy(), u_base, []
            while pendentes:
                locs = [[atual['lon'], atual['lat']]] + [[p['lon'], p['lat']] for p in pendentes]
                dm = ors_client.distance_matrix(locations=locs, profile='driving-car', metrics=['distance'])
                idx = dm['distances'][0][1:].index(min(dm['distances'][0][1:]))
                proximo = pendentes.pop(idx); ordenados.append(proximo); atual = proximo
        else: ordenados = pts_gps

        rota = [u_base] + ordenados + [u_base]
        tab, lin, km, tempo = [], [], 0, 0
        
        # Linha de Saída da Matriz
        tab.append({"Ordem": "SAÍDA", "Local": u_base['endereco'], "Dist.": "-", "Tempo": "-", "lat": u_base['lat'], "lon": u_base['lon']})

        for i in range(len(rota) - 1):
            A, B = rota[i], rota[i+1]
            dr = ors_client.directions(coordinates=[[A['lon'], A['lat']], [B['lon'], B['lat']]], profile='driving-car', format='geojson')
            s = dr['features'][0]['properties']['summary']
            d, t = round(s['distance']/1000, 2), round(s['duration']/60)
            km += d; tempo += t
            lin.extend([[c[1], c[0]] for c in dr['features'][0]['geometry']['coordinates']])
            
            lbl = "RETORNO" if i == len(rota)-2 else f"{i+1}ª PARADA"
            tab.append({"Ordem": lbl, "Local": B['endereco'], "Dist.": f"{d} km", "Tempo": f"{t} min", "lat": B['lat'], "lon": B['lon']})

        st.session_state.v159 = {"t": tab, "l": lin, "k": round(km, 2), "m": tempo}

# --- 5. EXIBIÇÃO ---
if "v159" in st.session_state:
    res = st.session_state.v159
    st.header(f"📊 Resumo: {res['k']} km | {res['m']} min")
    
    c1, c2 = st.columns([1.2, 1])
    with c1:
        st.dataframe(pd.DataFrame(res['t']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        # Link WhatsApp corrigido
        urls = [f"{p['lat']},{p['lon']}" for p in res['t']]
        link_g = f"https://www.google.com/maps/dir/{'/'.join(urls)}"
        st.link_button("🟢 WHATSAPP", f"https://api.whatsapp.com/send?text={urllib.parse.quote(link_g)}", use_container_width=True)

    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=13)
        folium.PolyLine(res['l'], color="red", weight=5).add_to(m)
        for p in res['t']:
            folium.Marker(
                [p['lat'], p['lon']], 
                popup=f"<b>{p['Ordem']}</b><br>{p['Local']}", # Ordem primeiro no popup
                icon=folium.Icon(color="green" if "Matriz" in p['Local'] else "blue")
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
