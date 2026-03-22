import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import urllib.parse

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Tecnolab Logística V15.8", layout="wide", page_icon="🧪")

@st.cache_data(show_spinner=False)
def get_coords_cep(cep_raw, num_raw, _ors_key):
    """
    Função de busca ultra-resistente. Tenta 3 níveis de precisão.
    """
    try:
        cep = "".join(filter(str.isdigit, str(cep_raw))).strip()
        num = "".join(filter(str.isdigit, str(num_raw))).strip()
        if len(cep) != 8: return None
        
        # 1. ViaCEP: Garante o nome correto (ex: Rua Columbia) para a tabela
        v_res = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=5).json()
        if "erro" in v_res: return None
        
        logradouro = v_res.get('logradouro', '')
        bairro = v_res.get('bairro', '')
        cidade = v_res.get('localidade', '')

        # 2. Busca Geográfica no ORS
        url = "https://api.openrouteservice.org/geocode/search"
        headers = {'Authorization': _ors_key}
        
        # Lista de tentativas da mais precisa para a mais genérica
        tentativas = [
            f"{cep}, {num}, Brasil",              # 1. CEP + Número
            f"{logradouro}, {num}, {cidade}, SP",  # 2. Nome da Rua + Número
            f"{cep}, Brasil"                       # 3. Apenas o CEP (Fallback)
        ]

        for texto in tentativas:
            params = {
                'api_key': _ors_key,
                'text': texto,
                'size': 1,
                'boundary.circle.lat': -23.6912,
                'boundary.circle.lon': -46.5594,
                'boundary.circle.radius': 50
            }
            resp = requests.get(url, params=params).json()
            
            if resp.get('features'):
                feat = resp['features'][0]
                # Verificação Anti-Coimbra: Se o GPS retornar Coimbra mas o ViaCEP diz Columbia,
                # ignoramos esta feature e tentamos a próxima (ou buscamos só o CEP)
                label_encontrado = feat['properties'].get('label', '').lower()
                if "coimbra" in label_encontrado and "columbia" in logradouro.lower() and texto != tentativas[-1]:
                    continue # Pula para a próxima tentativa (apenas CEP)
                
                coords = feat['geometry']['coordinates']
                return {
                    "lat": coords[1], "lon": coords[0], 
                    "endereco": f"{logradouro}, {num} - {bairro}", 
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
    st.error("Erro na ORS_KEY."); st.stop()

u_base = {"endereco": "Unidade Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 3. SIDEBAR ---
with st.sidebar:
    st.title("🚚 Roteirizador")
    modo = st.radio("Método:", ["Ordem Digitada", "Otimizar Caminho"])
    st.divider()
    
    inputs_validados = []
    for i in range(5):
        c1, c2 = st.columns([2, 1])
        with c1:
            ce = st.text_input(f"CEP {i+1}", key=f"f_cep_{i}", placeholder="00000000")
        with c2:
            nu = st.text_input(f"Nº", key=f"f_num_{i}", placeholder="123")
        if ce:
            inputs_validados.append({"cep": ce, "num": nu})

    st.divider()
    col_g, col_l = st.columns(2)
    with col_g:
        btn_gerar = st.button("🚀 GERAR", use_container_width=True, type="primary")
    with col_l:
        if st.button("🗑️ LIMPAR", use_container_width=True):
            for k in list(st.session_state.keys()):
                if k.startswith("f_") or "v158" in k:
                    del st.session_state[k]
            st.rerun()

# --- 4. LOGÍSTICA ---
if btn_gerar and inputs_validados:
    pts_gps = []
    for item in inputs_validados:
        res = get_coords_cep(item['cep'], item['num'], ORS_KEY)
        if res: pts_gps.append(res)
        else: st.error(f"Não localizamos o CEP: {item['cep']}")

    if pts_gps:
        # Ordenação
        if "Otimizar" in modo:
            pendentes, atual, ordenados = pts_gps.copy(), u_base, []
            while pendentes:
                locs = [[atual['lon'], atual['lat']]] + [[p['lon'], p['lat']] for p in pendentes]
                dm = ors_client.distance_matrix(locations=locs, profile='driving-car', metrics=['distance'])
                idx = dm['distances'][0][1:].index(min(dm['distances'][0][1:]))
                proximo = pendentes.pop(idx); ordenados.append(proximo); atual = proximo
        else:
            ordenados = pts_gps

        rota_total = [u_base] + ordenados + [u_base]
        tabela, linha, km_t, min_t = [], [], 0, 0
        
        # Ponto de Saída
        tabela.append({"Ordem": "SAÍDA", "Local": u_base['endereco'], "Dist. Trecho": "-", "Tempo": "-", "lat": u_base['lat'], "lon": u_base['lon']})

        for i in range(len(rota_total) - 1):
            A, B = rota_total[i], rota_total[i+1]
            dr = ors_client.directions(coordinates=[[A['lon'], A['lat']], [B['lon'], B['lat']]], profile='driving-car', format='geojson')
            s = dr['features'][0]['properties']['summary']
            d, t = round(s['distance']/1000, 2), round(s['duration']/60)
            km_t += d; min_t += t
            linha.extend([[c[1], c[0]] for c in dr['features'][0]['geometry']['coordinates']])
            
            lbl = "RETORNO" if i == len(rota_total)-2 else f"{i+1}ª PARADA"
            tabela.append({"Ordem": lbl, "Local": B['endereco'], "Dist. Trecho": f"{d} km", "Tempo": f"{t} min", "lat": B['lat'], "lon": B['lon']})

        st.session_state.v158 = {"t": tabela, "l": linha, "k": round(km_t, 2), "m": min_t}

# --- 5. EXIBIÇÃO ---
if "v158" in st.session_state:
    r = st.session_state.v158
    st.header(f"📊 Resumo: {r['k']} km | {r['m']} min")
    
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.dataframe(pd.DataFrame(r['t']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        # Link Google Maps
        u_list = [f"{p['lat']},{p['lon']}" for p in r['t']]
        link = f"https://www.google.com/maps/dir/{'/'.join(u_list)}"
        st.link_button("🟢 WHATSAPP / GPS", f"https://api.whatsapp.com/send?text={urllib.parse.quote(link)}", use_container_width=True)

    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=13)
        folium.PolyLine(r['l'], color="blue", weight=5).add_to(m)
        for p in r['t']:
            folium.Marker(
                [p['lat'], p['lon']], 
                popup=f"<b>{p['Ordem']}</b><br>{p['Local']}",
                icon=folium.Icon(color="green" if p['Ordem'] in ["SAÍDA", "RETORNO"] else "blue")
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
