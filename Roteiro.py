import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import urllib.parse

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Tecnolab Logística V15.3", layout="wide", page_icon="🧪")

# --- 2. FUNÇÃO DE BUSCA REFORÇADA (FOCO EM RUA COLUMBIA 09241-000) ---
@st.cache_data(show_spinner=False)
def get_coords_cep(cep_raw, num_raw, _ors_key):
    try:
        # Limpeza de caracteres não numéricos
        cep = "".join(filter(str.isdigit, str(cep_raw)))
        num = "".join(filter(str.isdigit, str(num_raw)))
        
        if len(cep) != 8: return None
        
        # 1. Busca nome no ViaCEP (para a tabela)
        v_res = requests.get(f"https://viacep.com.br/ws/{cep}/json/").json()
        if "erro" in v_res: return None
        
        logradouro = v_res.get('logradouro', '')
        bairro = v_res.get('bairro', '')
        cidade = v_res.get('localidade', '')

        # 2. BUSCA NO ORS (Tentativa 1: CEP + Número)
        # O uso do postalcode como filtro evita a confusão fonética (Columbia x Coimbra)
        url = "https://api.openrouteservice.org/geocode/search"
        params = {
            'api_key': _ors_key,
            'text': f"{cep}, {num}, Brasil",
            'size': 1,
            'layers': 'address',
            'boundary.circle.lat': -23.6912,
            'boundary.circle.lon': -46.5594,
            'boundary.circle.radius': 50
        }

        resp = requests.get(url, params=params).json()
        
        # Se falhar a busca por texto direto, tentamos buscar pelo nome da rua vindo do ViaCEP
        if not resp.get('features'):
            params['text'] = f"{logradouro}, {num}, {cidade}, Brasil"
            resp = requests.get(url, params=params).json()

        if resp.get('features'):
            feat = resp['features'][0]
            coords = feat['geometry']['coordinates']
            return {
                "lat": coords[1], 
                "lon": coords[0], 
                "endereco": f"{logradouro}, {num} - {bairro}, {cidade}", 
                "cep": cep
            }
        return None
    except:
        return None

# --- 3. SETUP API ---
try:
    ORS_KEY = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=ORS_KEY)
except:
    st.error("Erro: Verifique a ORS_KEY no Secrets."); st.stop()

u_base = {"endereco": "Tecnolab Matriz (SBC)", "lat": -23.6912, "lon": -46.5594}

# --- 4. SIDEBAR (INTERFACE) ---
with st.sidebar:
    st.title("🚚 Roteirizador")
    modo = st.radio("Método:", ["Ordem Digitada", "Otimizar Caminho"])
    st.divider()
    
    inputs_validados = []
    for i in range(5):
        c1, c2 = st.columns([2, 1])
        with c1:
            # Chaves com prefixo 'key_' para resetar no botão limpar
            c_val = st.text_input(f"CEP {i+1}", key=f"key_cep_{i}")
        with c2:
            n_val = st.text_input(f"Nº", key=f"key_num_{i}")
        
        if c_val:
            inputs_validados.append({"cep": c_val, "num": n_val})

    st.divider()
    col_g, col_l = st.columns(2)
    with col_g:
        btn_gerar = st.button("🚀 GERAR", use_container_width=True, type="primary")
    with col_l:
        if st.button("🗑️ LIMPAR", use_container_width=True):
            # Limpa especificamente as chaves dos campos de texto
            for k in list(st.session_state.keys()):
                if "key_" in k or "final_res" in k:
                    del st.session_state[k]
            st.rerun()

# --- 5. LOGÍSTICA ---
if btn_gerar and inputs_validados:
    pts_gps = []
    with st.spinner("Processando..."):
        for item in inputs_validados:
            res = get_coords_cep(item['cep'], item['num'], ORS_KEY)
            if res: pts_gps.append(res)
            else: st.error(f"Não achamos o CEP: {item['cep']}")

    if pts_gps:
        # Ordenação Inteligente (Opcional)
        if "Otimizar" in modo:
            pendentes = pts_gps.copy()
            atual = u_base
            ordenados = []
            while pendentes:
                locs = [[atual['lon'], atual['lat']]] + [[p['lon'], p['lat']] for p in pendentes]
                dm = ors_client.distance_matrix(locations=locs, profile='driving-car', metrics=['distance'])
                idx = dm['distances'][0][1:].index(min(dm['distances'][0][1:]))
                proximo = pendentes.pop(idx)
                ordenados.append(proximo)
                atual = proximo
        else:
            ordenados = pts_gps

        # Percurso Final (Base -> Pontos -> Base)
        rota = [u_base] + ordenados + [u_base]
        tabela, linha, km = [], [], 0

        for i in range(len(rota) - 1):
            A, B = rota[i], rota[i+1]
            # Chamada para traçar a linha no mapa
            direcoes = ors_client.directions(coordinates=[[A['lon'], A['lat']], [B['lon'], B['lat']]], profile='driving-car', format='geojson')
            km += direcoes['features'][0]['properties']['summary']['distance'] / 1000
            linha.extend([[c[1], c[0]] for c in direcoes['features'][0]['geometry']['coordinates']])
            
            label = "Saída" if i == 0 else (f"{i}ª Parada")
            tabela.append({"Ordem": label, "Local": B['endereco'] if i < len(rota)-2 else "Retorno à Matriz", "lat": B['lat'], "lon": B['lon']})

        st.session_state.final_res = {"tabela": tabela, "linha": linha, "km": round(km, 2)}

# --- 6. EXIBIÇÃO ---
if "final_res" in st.session_state:
    data = st.session_state.final_res
    st.subheader(f"📊 Distância: {data['km']} km")
    
    c1, c2 = st.columns([1, 1.3])
    with c1:
        st.dataframe(pd.DataFrame(data['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        
        # Link Google Maps
        c_str = [f"{p['lat']},{p['lon']}" for p in data['tabela']]
        link = f"https://www.google.com/maps/dir/{u_base['lat']},{u_base['lon']}/{'/'.join(c_str)}"
        st.link_button("📲 ENVIAR PARA WHATSAPP / GPS", f"https://api.whatsapp.com/send?text={urllib.parse.quote(f'Roteiro: {link}')}", use_container_width=True)

    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(data['linha'], color="blue", weight=5).add_to(m)
        for p in data['tabela']:
            folium.Marker([p['lat'], p['lon']], popup=p['Local'], icon=folium.Icon(color="red" if "Matriz" in p['Local'] else "blue")).add_to(m)
        st_folium(m, use_container_width=True, height=500)
