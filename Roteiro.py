import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import urllib.parse

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Tecnolab Logística V15.5", layout="wide", page_icon="🧪")

@st.cache_data(show_spinner=False)
def get_coords_cep(cep_raw, num_raw, _ors_key):
    try:
        # 1. Limpeza rigorosa dos inputs
        cep = "".join(filter(str.isdigit, str(cep_raw)))
        num = "".join(filter(str.isdigit, str(num_raw)))
        if len(cep) != 8: return None
        
        # 2. Consulta ViaCEP (Fonte primária de texto)
        v_res = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=5).json()
        if "erro" in v_res: return None
        
        logradouro = v_res.get('logradouro')
        bairro = v_res.get('bairro')
        cidade = v_res.get('localidade')

        # 3. ESTRATÉGIA DE BUSCA GEOGRÁFICA (3 Tentativas)
        url = "https://api.openrouteservice.org/geocode/search"
        common_params = {
            'api_key': _ors_key,
            'size': 1,
            'boundary.circle.lat': -23.6912,
            'boundary.circle.lon': -46.5594,
            'boundary.circle.radius': 50
        }

        # Tentativa A: CEP + Número (Mais preciso para Rua Columbia)
        params_a = {**common_params, 'text': f"{cep}, {num}, Brasil", 'layers': 'address'}
        resp = requests.get(url, params=params_a).json()

        # Tentativa B: Nome da Rua + Número + Cidade (Fallback se o CEP não estiver mapeado no ORS)
        if not resp.get('features'):
            params_b = {**common_params, 'text': f"{logradouro}, {num}, {cidade}, SP", 'layers': 'address'}
            resp = requests.get(url, params=params_b).json()

        # Tentativa C: Apenas o CEP (Último recurso, cai no meio da rua)
        if not resp.get('features'):
            params_c = {**common_params, 'text': f"{cep}, Brasil"}
            resp = requests.get(url, params=params_c).json()

        if resp.get('features'):
            coords = resp['features'][0]['geometry']['coordinates']
            return {
                "lat": coords[1], "lon": coords[0], 
                "endereco": f"{logradouro}, {num} - {bairro}", 
                "cidade": cidade
            }
        return None
    except Exception as e:
        return None

# --- 2. SETUP ---
ORS_KEY = st.secrets["ORS_KEY"]
ors_client = client.Client(key=ORS_KEY)
u_base = {"endereco": "Unidade Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 3. SIDEBAR ---
with st.sidebar:
    st.title("🚚 Gestão de Rotas")
    modo = st.radio("Método:", ["Ordem Digitada", "Otimizar Caminho"])
    st.divider()
    
    inputs = []
    for i in range(5):
        c1, c2 = st.columns([2, 1])
        with c1: ce = st.text_input(f"CEP {i+1}", key=f"z_cep_{i}")
        with c2: nu = st.text_input(f"Nº", key=f"z_num_{i}")
        if ce: inputs.append({"cep": ce, "num": nu})

    btn_gerar = st.button("🚀 GERAR ROTEIRO", use_container_width=True, type="primary")
    if st.button("🗑️ LIMPAR TUDO", use_container_width=True):
        for k in list(st.session_state.keys()):
            if "z_" in k or "v154" in k: del st.session_state[k]
        st.rerun()

# --- 4. LOGÍSTICA ---
if btn_gerar and inputs:
    pts_gps = []
    for item in inputs:
        res = get_coords_cep(item['cep'], item['num'], ORS_KEY)
        if res: pts_gps.append(res)
        else: st.error(f"CEP {item['cep']} não localizado.")

    if pts_gps:
        # Inteligência de Rota
        if "Otimizar" in modo:
            pendentes, atual, ordenados = pts_gps.copy(), u_base, []
            while pendentes:
                locs = [[atual['lon'], atual['lat']]] + [[p['lon'], p['lat']] for p in pendentes]
                dm = ors_client.distance_matrix(locations=locs, profile='driving-car', metrics=['distance'])
                idx = dm['distances'][0][1:].index(min(dm['distances'][0][1:]))
                proximo = pendentes.pop(idx); ordenados.append(proximo); atual = proximo
        else: ordenados = pts_gps

        # Construção do Itinerário (Inicia com Matriz)
        rota_total = [u_base] + ordenados + [u_base]
        tabela_final, geometria, total_km, total_min = [], [], 0, 0
        
        # Primeira linha: Saída
        tabela_final.append({"Ordem": "SAÍDA", "Local": u_base['endereco'], "Dist. Trecho": "-", "Tempo": "-", "lat": u_base['lat'], "lon": u_base['lon']})

        for i in range(len(rota_total) - 1):
            A, B = rota_total[i], rota_total[i+1]
            dir_res = ors_client.directions(coordinates=[[A['lon'], A['lat']], [B['lon'], B['lat']]], profile='driving-car', format='geojson')
            
            summary = dir_res['features'][0]['properties']['summary']
            d_km = round(summary['distance'] / 1000, 2)
            t_min = round(summary['duration'] / 60)
            
            total_km += d_km
            total_min += t_min
            geometria.extend([[c[1], c[0]] for c in dir_res['features'][0]['geometry']['coordinates']])
            
            label = "RETORNO" if i == len(rota_total) - 2 else f"{i+1}ª PARADA"
            tabela_final.append({
                "Ordem": label, "Local": B['endereco'], 
                "Dist. Trecho": f"{d_km} km", "Tempo": f"{t_min} min",
                "lat": B['lat'], "lon": B['lon']
            })

        st.session_state.v154 = {"tabela": tabela_final, "linha": geometria, "km": round(total_km, 2), "min": total_min}

# --- 5. EXIBIÇÃO ---
if "v154" in st.session_state:
    d = st.session_state.v154
    st.header(f"📊 Resumo: {d['km']} km | Tempo Estimado: {d['min']} min")
    
    c1, c2 = st.columns([1.1, 1])
    with c1:
        # Tabela Detalhada
        st.dataframe(pd.DataFrame(d['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        
        # WhatsApp com endereços e Link
        msg = f"🚚 *ROTEIRO TECNOLAB*\nTotal: {d['km']}km\n\n"
        coords_url = []
        for p in d['tabela']:
            msg += f"*{p['Ordem']}*: {p['Local']}\n"
            coords_url.append(f"{p['lat']},{p['lon']}")
        
        # Link Google Maps (Corrigido para navegação exata)
        link_google = f"https://www.google.com/maps/dir/{'/'.join(coords_url)}"
        msg += f"\n📍 *GPS:* {link_google}"
        
        st.link_button("🟢 ENVIAR PARA WHATSAPP", f"https://api.whatsapp.com/send?text={urllib.parse.quote(msg)}", use_container_width=True)

    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(d['linha'], color="red", weight=5, opacity=0.7).add_to(m)
        
        # Marcadores com Ordem primeiro no Pop-up
        for p in d['tabela']:
            cor = "green" if p['Ordem'] in ["SAÍDA", "RETORNO"] else "blue"
            folium.Marker(
                [p['lat'], p['lon']],
                popup=folium.Popup(f"<b>{p['Ordem']}</b><br>{p['Local']}", max_width=300),
                tooltip=p['Ordem'],
                icon=folium.Icon(color=cor, icon='info-sign')
            ).add_to(m)
        
        st_folium(m, use_container_width=True, height=550)
