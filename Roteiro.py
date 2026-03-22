import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import urllib.parse

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Tecnolab V15.6", layout="wide", page_icon="🧪")

@st.cache_data(show_spinner=False)
def get_coords_cep(cep_raw, num_raw, _ors_key):
    try:
        cep = "".join(filter(str.isdigit, str(cep_raw)))
        num = "".join(filter(str.isdigit, str(num_raw)))
        if len(cep) != 8: return None
        
        # 1. ViaCEP para o texto correto
        v_res = requests.get(f"https://viacep.com.br/ws/{cep}/json/").json()
        if "erro" in v_res: return None
        logradouro = v_res.get('logradouro')
        
        # 2. Busca Geográfica (Filtro Anti-Coimbra)
        url = "https://api.openrouteservice.org/geocode/search"
        params = {
            'api_key': _ors_key,
            'text': f"{cep}, {num}, Brasil",
            'size': 1,
            'layers': 'address',
            'boundary.circle.lat': -23.6912,
            'boundary.circle.lon': -46.5594,
            'boundary.circle.radius': 40
        }
        resp = requests.get(url, params=params).json()
        
        # Validação: Se o ORS retornar "Coimbra" em vez de "Columbia", forçamos busca por CEP
        if resp.get('features'):
            nome_maps = resp['features'][0]['properties'].get('label', '').lower()
            if "coimbra" in nome_maps and "columbia" in logradouro.lower():
                params['text'] = f"{cep}, Brasil" # Busca só pelo CEP
                resp = requests.get(url, params=params).json()

        if resp.get('features'):
            coords = resp['features'][0]['geometry']['coordinates']
            return {
                "lat": coords[1], "lon": coords[0], 
                "endereco": f"{logradouro}, {num} - {v_res.get('bairro')}", 
                "cidade": v_res.get('localidade')
            }
        return None
    except: return None

# --- 2. SETUP ---
ORS_KEY = st.secrets["ORS_KEY"]
ors_client = client.Client(key=ORS_KEY)
u_base = {"endereco": "Unidade Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 3. SIDEBAR (RESET TOTAL CORRIGIDO) ---
with st.sidebar:
    st.title("🚚 Roteirizador")
    
    # Criamos um formulário que pode ser resetado
    with st.form("meu_formulario", clear_on_submit=True):
        modo = st.radio("Método:", ["Ordem Digitada", "Otimizar Caminho"])
        st.divider()
        
        input_data = []
        for i in range(5):
            c1, c2 = st.columns([2, 1])
            with c1: ce = st.text_input(f"CEP {i+1}", placeholder="00000000")
            with c2: nu = st.text_input(f"Nº {i+1}", placeholder="123")
            if ce: input_data.append({"cep": ce, "num": nu})
        
        st.divider()
        # O botão dentro do formulário processa os dados
        btn_gerar = st.form_submit_button("🚀 GERAR ROTEIRO", use_container_width=True)

    # Botão de limpar fora do formulário para resetar o session_state
    if st.button("🗑️ LIMPAR TUDO", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# --- 4. LOGÍSTICA ---
# Como usamos formulário, precisamos salvar os inputs na sessão para não sumirem
if btn_gerar and input_data:
    pts_gps = []
    for item in input_data:
        res = get_coords_cep(item['cep'], item['num'], ORS_KEY)
        if res: pts_gps.append(res)
    
    if pts_gps:
        if "Otimizar" in modo:
            pendentes, atual, ordenados = pts_gps.copy(), u_base, []
            while pendentes:
                locs = [[atual['lon'], atual['lat']]] + [[p['lon'], p['lat']] for p in pendentes]
                dm = ors_client.distance_matrix(locations=locs, profile='driving-car', metrics=['distance'])
                idx = dm['distances'][0][1:].index(min(dm['distances'][0][1:]))
                proximo = pendentes.pop(idx); ordenados.append(proximo); atual = proximo
        else: ordenados = pts_gps

        rota_total = [u_base] + ordenados + [u_base]
        tabela, geometria, km_total, min_total = [], [], 0, 0
        
        tabela.append({"Ordem": "SAÍDA", "Local": u_base['endereco'], "Dist.": "-", "Tempo": "-", "lat": u_base['lat'], "lon": u_base['lon']})

        for i in range(len(rota_total) - 1):
            A, B = rota_total[i], rota_total[i+1]
            dr = ors_client.directions(coordinates=[[A['lon'], A['lat']], [B['lon'], B['lat']]], profile='driving-car', format='geojson')
            sum_ = dr['features'][0]['properties']['summary']
            d, t = round(sum_['distance']/1000, 2), round(sum_['duration']/60)
            km_total += d; min_total += t
            geometria.extend([[c[1], c[0]] for c in dr['features'][0]['geometry']['coordinates']])
            
            label = "RETORNO" if i == len(rota_total)-2 else f"{i+1}ª PARADA"
            tabela.append({"Ordem": label, "Local": B['endereco'], "Dist.": f"{d} km", "Tempo": f"{t} min", "lat": B['lat'], "lon": B['lon']})

        st.session_state.v156 = {"t": tabela, "g": geometria, "k": round(km_total, 2), "m": min_total}

# --- 5. EXIBIÇÃO ---
if "v156" in st.session_state:
    res = st.session_state.v156
    st.header(f"📊 Resumo: {res['k']} km | {res['m']} min")
    
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.dataframe(pd.DataFrame(res['t']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        coords_u = [f"{p['lat']},{p['lon']}" for p in res['t']]
        link = f"https://www.google.com/maps/dir/{'/'.join(coords_u)}"
        st.link_button("🟢 WHATSAPP / GPS", f"https://api.whatsapp.com/send?text={urllib.parse.quote(link)}", use_container_width=True)

    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=13)
        folium.PolyLine(res['g'], color="red", weight=5).add_to(m)
        for p in res['t']:
            folium.Marker([p['lat'], p['lon']], popup=f"<b>{p['Ordem']}</b><br>{p['Local']}", icon=folium.Icon(color="blue")).add_to(m)
        st_folium(m, use_container_width=True, height=500)
