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
        # Limpeza total de caracteres
        cep = "".join(filter(str.isdigit, str(cep_raw)))
        num = "".join(filter(str.isdigit, str(num_raw)))
        if len(cep) != 8: return None
        
        # 1. Consulta ViaCEP (Fonte da Verdade para o Endereço)
        v_res = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=5).json()
        if "erro" in v_res: return None
        
        logradouro = v_res.get('logradouro')
        bairro = v_res.get('bairro')
        cidade = v_res.get('localidade')

        # 2. TENTATIVAS DE LOCALIZAÇÃO (GPS)
        url = "https://api.openrouteservice.org/geocode/search"
        headers = {'Authorization': _ors_key}
        
        # Tentativa 1: CEP + Número (A mais precisa para evitar Rua Coimbra)
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

        # Tentativa 2: Nome da Rua + Número + Cidade (Se o CEP falhar no motor do mapa)
        if not resp.get('features'):
            params['text'] = f"{logradouro}, {num}, {cidade}, SP"
            resp = requests.get(url, params=params).json()

        # Tentativa 3: Apenas o CEP (Último recurso)
        if not resp.get('features'):
            params['text'] = f"{cep}, Brasil"
            params.pop('layers', None)
            resp = requests.get(url, params=params).json()

        if resp.get('features'):
            feat = resp['features'][0]
            coords = feat['geometry']['coordinates']
            return {
                "lat": coords[1], "lon": coords[0], 
                "endereco": f"{logradouro}, {num} - {bairro}", 
                "cidade": cidade
            }
        return None
    except Exception as e:
        st.error(f"Erro técnico na busca: {e}")
        return None

# --- 2. SETUP ---
ORS_KEY = st.secrets["ORS_KEY"]
ors_client = client.Client(key=ORS_KEY)
u_base = {"endereco": "Unidade Matriz SBC", "lat": -23.6912, "lon": -46.5594}

# --- 3. SIDEBAR (CORREÇÃO DO BOTÃO LIMPAR) ---
# --- Na seção da Sidebar ---
with st.sidebar:
    st.title("🚚 Gestão de Rotas")
    modo = st.radio("Método:", ["Ordem Digitada", "Otimizar Caminho"])
    st.divider()
    
    inputs = []
    # Usamos o range para criar os campos
    for i in range(5):
        c1, c2 = st.columns([2, 1])
        # A chave (key) deve ser única. Se ela for deletada do session_state, o campo reseta.
        with c1: 
            ce = st.text_input(f"CEP {i+1}", key=f"z_cep_{i}")
        with c2: 
            nu = st.text_input(f"Nº", key=f"z_num_{i}")
        
        if ce: 
            inputs.append({"cep": ce, "num": nu})

    st.divider()
    
    col_gerar, col_limpar = st.columns(2)
    
    with col_gerar:
        btn_gerar = st.button("🚀 GERAR", use_container_width=True, type="primary")
    
    with col_limpar:
        if st.button("🗑️ LIMPAR", use_container_width=True):
            # 1. Limpa todas as chaves de input e de resultados
            for key in list(st.session_state.keys()):
                if key.startswith("z_") or "v15" in key:
                    del st.session_state[key]
            # 2. Força o reinício imediato para limpar a tela
            st.rerun()

# --- 4. LOGÍSTICA ---
if btn_gerar and inputs:
    pts_gps = []
    for item in inputs:
        res = get_coords_cep(item['cep'], item['num'], ORS_KEY)
        if res: pts_gps.append(res)
        else: st.error(f"Erro: CEP {item['cep']} não localizado.")

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
        tabela_final, geometria, total_km, total_min = [], [], 0, 0
        
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

        st.session_state.v155 = {"tabela": tabela_final, "linha": geometria, "km": round(total_km, 2), "min": total_min}

# --- 5. EXIBIÇÃO ---
if "v155" in st.session_state:
    d = st.session_state.v155
    st.header(f"📊 Resumo: {d['km']} km | Tempo Estimado: {d['min']} min")
    
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.dataframe(pd.DataFrame(d['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        
        # WhatsApp Link
        msg = f"🚚 *ROTEIRO TECNOLAB*\nTotal: {d['km']}km\n\n"
        coords_url = []
        for p in d['tabela']:
            msg += f"*{p['Ordem']}*: {p['Local']}\n"
            coords_url.append(f"{p['lat']},{p['lon']}")
        
        link_google = f"https://www.google.com/maps/dir/{'/'.join(coords_url)}"
        msg += f"\n📍 *GPS:* {link_google}"
        st.link_button("🟢 ENVIAR PARA WHATSAPP", f"https://api.whatsapp.com/send?text={urllib.parse.quote(msg)}", use_container_width=True)

    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=14)
        folium.PolyLine(d['linha'], color="red", weight=5, opacity=0.7).add_to(m)
        
        for p in d['tabela']:
            cor = "green" if p['Ordem'] in ["SAÍDA", "RETORNO"] else "blue"
            folium.Marker(
                [p['lat'], p['lon']],
                popup=f"<b>{p['Ordem']}</b><br>{p['Local']}", # Ordem primeiro no popup
                tooltip=p['Ordem'],
                icon=folium.Icon(color=cor, icon='info-sign')
            ).add_to(m)
        
        st_folium(m, use_container_width=True, height=550)
