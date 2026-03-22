import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import urllib.parse

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Tecnolab Logística V16.0", layout="wide", page_icon="🧪")

@st.cache_data(show_spinner=False)
def get_coords_cep(cep_raw, num_raw, _ors_key):
    """
    Busca robusta: Tenta endereço completo -> Se falhar ou der erro de nome -> Tenta apenas CEP.
    """
    try:
        cep = "".join(filter(str.isdigit, str(cep_raw))).strip()
        num = "".join(filter(str.isdigit, str(num_raw))).strip()
        if len(cep) != 8: return None
        
        # 1. ViaCEP: Fonte oficial para o nome da rua (Tabela)
        v_res = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=5).json()
        if "erro" in v_res: return None
        rua_viacep = v_res.get('logradouro', '')
        bairro = v_res.get('bairro', '')
        cidade = v_res.get('localidade', '')

        # 2. Busca Geográfica (GPS)
        url = "https://api.openrouteservice.org/geocode/search"
        
        # Tentativa A: Endereço Completo
        params = {
            'api_key': _ors_key,
            'text': f"{cep}, {num}, Brasil",
            'size': 1,
            'boundary.circle.lat': -23.6912,
            'boundary.circle.lon': -46.5594,
            'boundary.circle.radius': 40
        }
        
        resp = requests.get(url, params=params).json()
        
        # Validação: Se não achou NADA ou se achou a 'Rua Coimbra' por erro fonético
        achou_algo = resp.get('features') and len(resp['features']) > 0
        if achou_algo:
            label_mapa = resp['features'][0]['properties'].get('label', '').lower()
            # Se o ViaCEP diz Columbia e o mapa diz Coimbra, força o fallback
            if "coimbra" in label_mapa and "columbia" in rua_viacep.lower():
                achou_algo = False 

        # Tentativa B: Fallback para o CEP Puro (Garante que o pino caia na rua certa)
        if not achou_algo:
            params['text'] = f"{cep}, Brasil"
            resp = requests.get(url, params=params).json()

        if resp.get('features'):
            coords = resp['features'][0]['geometry']['coordinates']
            return {
                "lat": coords[1], "lon": coords[0], 
                "endereco": f"{rua_viacep}, {num} - {bairro}", 
                "cidade": cidade
            }
        return None
    except:
        return None

# --- 2. SETUP API ---
try:
    ORS_KEY = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=ORS_KEY)
except:
    st.error("Erro: Verifique a ORS_KEY no Secrets."); st.stop()

u_base = {"endereco": "Unidade Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 3. SIDEBAR (CONTROLE DE RESET) ---
with st.sidebar:
    st.title("🚚 Roteirizador")
    
    # Trigger para limpar os campos mudando as keys
    if 'limpar_cont' not in st.session_state:
        st.session_state.limpar_cont = 0

    modo = st.radio("Método:", ["Ordem Digitada", "Otimizar Caminho"], key=f"m_{st.session_state.limpar_cont}")
    st.divider()
    
    entradas = []
    for i in range(5):
        c1, c2 = st.columns([2, 1])
        with c1:
            ce = st.text_input(f"CEP {i+1}", key=f"c_{i}_{st.session_state.limpar_cont}", placeholder="00000000")
        with c2:
            nu = st.text_input(f"Nº", key=f"n_{i}_{st.session_state.limpar_cont}", placeholder="S/N")
        if ce: 
            entradas.append({"cep": ce, "num": nu})

    st.divider()
    col_g, col_l = st.columns(2)
    with col_g:
        btn_gerar = st.button("🚀 GERAR", use_container_width=True, type="primary")
    with col_l:
        if st.button("🗑️ LIMPAR", use_container_width=True):
            if "res_v16" in st.session_state: del st.session_state.res_v16
            st.session_state.limpar_cont += 1 # Muda as keys para resetar campos
            st.rerun()

# --- 4. PROCESSAMENTO ---
if btn_gerar and entradas:
    pts_gps = []
    for item in entradas:
        res = get_coords_cep(item['cep'], item['num'], ORS_KEY)
        if res: pts_gps.append(res)
        else: st.error(f"CEP {item['cep']} não localizado nos mapas.")

    if pts_gps:
        if "Otimizar" in modo:
            pend, atu, ord_list = pts_gps.copy(), u_base, []
            while pend:
                locs = [[atu['lon'], atu['lat']]] + [[p['lon'], p['lat']] for p in pend]
                dm = ors_client.distance_matrix(locations=locs, profile='driving-car', metrics=['distance'])
                idx = dm['distances'][0][1:].index(min(dm['distances'][0][1:]))
                proximo = pend.pop(idx); ord_list.append(proximo); atu = proximo
        else:
            ord_list = pts_gps

        rota_final = [u_base] + ord_list + [u_base]
        tab, lin, km, t_min = [], [], 0, 0
        
        # Saída Matriz
        tab.append({"Ordem": "SAÍDA", "Local": u_base['endereco'], "Dist. Trecho": "-", "Tempo": "-", "lat": u_base['lat'], "lon": u_base['lon']})

        for i in range(len(rota_final) - 1):
            A, B = rota_final[i], rota_final[i+1]
            dr = ors_client.directions(coordinates=[[A['lon'], A['lat']], [B['lon'], B['lat']]], profile='driving-car', format='geojson')
            s = dr['features'][0]['properties']['summary']
            d_km, d_min = round(s['distance']/1000, 2), round(s['duration']/60)
            km += d_km; t_min += d_min
            lin.extend([[c[1], c[0]] for c in dr['features'][0]['geometry']['coordinates']])
            
            lbl = "RETORNO" if i == len(rota_final)-2 else f"{i+1}ª PARADA"
            tab.append({"Ordem": lbl, "Local": B['endereco'], "Dist. Trecho": f"{d_km} km", "Tempo": f"{d_min} min", "lat": B['lat'], "lon": B['lon']})

        st.session_state.res_v16 = {"t": tab, "l": lin, "k": round(km, 2), "m": t_min}

# --- 5. EXIBIÇÃO ---
if "res_v16" in st.session_state:
    data = st.session_state.res_v16
    st.header(f"📊 Resumo: {data['k']} km | {data['m']} min")
    
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.dataframe(pd.DataFrame(data['t']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        # Link Google Maps
        u_str = [f"{p['lat']},{p['lon']}" for p in data['t']]
        link = f"https://www.google.com/maps/dir/{'/'.join(u_str)}"
        st.link_button("🟢 ENVIAR WHATSAPP / GPS", f"https://api.whatsapp.com/send?text={urllib.parse.quote(link)}", use_container_width=True)

    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=13)
        folium.PolyLine(data['l'], color="red", weight=5).add_to(m)
        for p in data['t']:
            folium.Marker(
                [p['lat'], p['lon']], 
                popup=f"<b>{p['Ordem']}</b><br>{p['Local']}",
                icon=folium.Icon(color="green" if p['Ordem'] in ["SAÍDA", "RETORNO"] else "blue")
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
