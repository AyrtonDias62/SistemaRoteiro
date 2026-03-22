import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import urllib.parse

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Tecnolab V15.7", layout="wide", page_icon="🧪")

@st.cache_data(show_spinner=False)
def get_coords_cep(cep_raw, num_raw, _ors_key):
    try:
        cep = "".join(filter(str.isdigit, str(cep_raw)))
        num = "".join(filter(str.isdigit, str(num_raw)))
        if len(cep) != 8: return None
        
        # 1. ViaCEP para garantir o nome "Rua Columbia" na tabela
        v_res = requests.get(f"https://viacep.com.br/ws/{cep}/json/").json()
        if "erro" in v_res: return None
        logradouro = v_res.get('logradouro')

        # 2. Busca Geográfica (Trava de Segurança para CEP 09241000)
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
        
        # Se o GPS retornar "Coimbra", forçamos a busca puramente pelo código postal
        if resp.get('features'):
            label_mapa = resp['features'][0]['properties'].get('label', '').lower()
            if "coimbra" in label_mapa and "columbia" in logradouro.lower():
                params['text'] = f"{cep}, Brasil"
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

# --- 3. SIDEBAR (CAMPOS VAZIOS E RESET) ---
with st.sidebar:
    st.title("🚚 Gestão de Rotas")
    
    # O segredo do reset é não usar 'value' e sim 'key'
    modo = st.radio("Método de Rota:", ["Ordem Digitada", "Otimizar Caminho"])
    st.divider()
    
    inputs_do_usuario = []
    # Criamos os 5 campos sem pré-preenchimento
    for i in range(5):
        c1, c2 = st.columns([2, 1])
        with c1:
            # Removido o 'value', deixamos apenas 'key'
            ce = st.text_input(f"CEP {i+1}", key=f"f_cep_{i}", placeholder="Digite o CEP")
        with c2:
            nu = st.text_input(f"Nº", key=f"f_num_{i}", placeholder="S/N")
        
        if ce:
            inputs_do_usuario.append({"cep": ce, "num": nu})

    st.divider()
    col_g, col_l = st.columns(2)
    
    with col_g:
        btn_gerar = st.button("🚀 GERAR", use_container_width=True, type="primary")
    
    with col_l:
        if st.button("🗑️ LIMPAR", use_container_width=True):
            # Deletar chaves do session_state limpa os campos instantaneamente
            for k in list(st.session_state.keys()):
                if k.startswith("f_") or "v157" in k:
                    del st.session_state[k]
            st.rerun()

# --- 4. LOGÍSTICA ---
if btn_gerar and inputs_do_usuario:
    pts_gps = []
    for item in inputs_do_usuario:
        res = get_coords_cep(item['cep'], item['num'], ORS_KEY)
        if res: pts_gps.append(res)
        else: st.error(f"CEP {item['cep']} não encontrado.")

    if pts_gps:
        if "Otimizar" in modo:
            pendentes, atual, ordenados = pts_gps.copy(), u_base, []
            while pendentes:
                locs = [[atual['lon'], atual['lat']]] + [[p['lon'], p['lat']] for p in pendentes]
                dm = ors_client.distance_matrix(locations=locs, profile='driving-car', metrics=['distance'])
                idx = dm['distances'][0][1:].index(min(dm['distances'][0][1:]))
                proximo = pendentes.pop(idx); ordenados.append(proximo); atual = proximo
        else:
            ordenados = pts_gps

        rota_final = [u_base] + ordenados + [u_base]
        tabela, linha, km_total, tempo_total = [], [], 0, 0
        
        # Linha de Saída obrigatória
        tabela.append({"Ordem": "SAÍDA", "Local": u_base['endereco'], "Dist. Trecho": "-", "Tempo": "-", "lat": u_base['lat'], "lon": u_base['lon']})

        for i in range(len(rota_final) - 1):
            A, B = rota_final[i], rota_final[i+1]
            dr = ors_client.directions(coordinates=[[A['lon'], A['lat']], [B['lon'], B['lat']]], profile='driving-car', format='geojson')
            
            s = dr['features'][0]['properties']['summary']
            d, t = round(s['distance']/1000, 2), round(s['duration']/60)
            km_total += d; tempo_total += t
            linha.extend([[c[1], c[0]] for c in dr['features'][0]['geometry']['coordinates']])
            
            lbl = "RETORNO" if i == len(rota_final)-2 else f"{i+1}ª PARADA"
            tabela.append({
                "Ordem": lbl, "Local": B['endereco'], 
                "Dist. Trecho": f"{d} km", "Tempo": f"{t} min",
                "lat": B['lat'], "lon": B['lon']
            })

        st.session_state.v157 = {"t": tabela, "l": linha, "k": round(km_total, 2), "m": tempo_total}

# --- 5. RESULTADOS ---
if "v157" in st.session_state:
    r = st.session_state.v157
    st.header(f"🏁 Roteiro: {r['k']} km | Estimativa: {r['m']} min")
    
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.dataframe(pd.DataFrame(r['t']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
        
        # Link WhatsApp
        msg = f"🚚 *TECNOLAB: ROTEIRO FINAL*\nDistância: {r['k']}km\n\n"
        urls = []
        for p in r['t']:
            msg += f"*{p['Ordem']}*: {p['Local']}\n"
            urls.append(f"{p['lat']},{p['lon']}")
        
        link_g = f"https://www.google.com/maps/dir/{'/'.join(urls)}"
        st.link_button("🟢 ENVIAR WHATSAPP / GPS", f"https://api.whatsapp.com/send?text={urllib.parse.quote(msg + chr(10) + '📍 Link: ' + link_g)}", use_container_width=True)

    with c2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=13)
        folium.PolyLine(r['l'], color="red", weight=5).add_to(m)
        for p in r['t']:
            # Pop-up agora mostra a Ordem Primeiro
            folium.Marker(
                [p['lat'], p['lon']], 
                popup=f"<b>{p['Ordem']}</b><br>{p['Local']}",
                icon=folium.Icon(color="green" if p['Ordem'] in ["SAÍDA", "RETORNO"] else "blue")
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
