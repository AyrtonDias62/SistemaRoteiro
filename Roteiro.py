import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium
import urllib.parse

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Roteirizador Tecnolab V15.0", layout="wide", page_icon="🚚")

# --- 2. FUNÇÃO DE BUSCA (PRECISÃO POR CEP) ---
@st.cache_data(show_spinner=False)
def get_coords_cep(cep, numero, _ors_key):
    """
    Busca coordenadas usando ViaCEP para o nome e ORS para GPS.
    Prioriza o CEP no texto de busca para evitar erros fonéticos (ex: Columbia vs Coimbra).
    """
    try:
        # Limpeza do CEP
        clean_cep = str(cep).replace('-', '').replace(' ', '').strip()
        if len(clean_cep) != 8: return None
        
        # Consulta ViaCEP (Fonte para o nome da rua)
        r = requests.get(f"https://viacep.com.br/ws/{clean_cep}/json/").json()
        if "erro" in r: return None
        
        logradouro = r.get('logradouro', '')
        cidade = r.get('localidade', '')
        bairro = r.get('bairro', '')

        # BUSCA TÉCNICA: CEP como primeiro termo evita confusão fonética de nomes de ruas
        texto_busca = f"{clean_cep}, {numero}, Brasil"

        url = "https://api.openrouteservice.org/geocode/search"
        params = {
            'api_key': _ors_key,
            'text': texto_busca,
            'size': 1,
            'boundary.circle.lat': -23.6912, # Centro em SBC
            'boundary.circle.lon': -46.5594,
            'boundary.circle.radius': 40,    # Raio de 40km (Grande SP/ABCD)
            'layers': 'address'              # Foca em números de porta
        }

        response = requests.get(url, params=params).json()
        
        if response and len(response['features']) > 0:
            coords = response['features'][0]['geometry']['coordinates']
            return {
                "lat": coords[1], 
                "lon": coords[0], 
                "endereco": f"{logradouro}, {numero} - {bairro}", 
                "cep": clean_cep
            }
        return None
    except:
        return None

# --- 3. SETUP API ---
try:
    ORS_KEY = st.secrets["ORS_KEY"]
    ors_client = client.Client(key=ORS_KEY)
except:
    st.error("Erro na ORS_KEY nos Secrets."); st.stop()

# Coordenada da Unidade Matriz
u_base = {"endereco": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594, "cep": "Matriz"}

# --- 4. INTERFACE (SIDEBAR) ---
with st.sidebar:
    st.header("🚚 Sistema Tecnolab")
    
    modo = st.selectbox("Comportamento do Roteiro:", [
        "1. Roteiro Travado (Ordem do Input)", 
        "2. Roteiro Inteligente (Otimizado)"
    ])
    
    st.divider()
    
    # Lista para armazenar o que o usuário digitou
    dados_input = []
    for i in range(5):
        col_cep, col_num = st.columns([2, 1])
        with col_cep:
            # Usamos o prefixo 'input_' para facilitar a limpeza depois
            c = st.text_input(f"CEP {i+1}", key=f"input_cep_{i}")
        with col_num:
            n = st.text_input(f"Nº", key=f"input_num_{i}")
        
        if c: 
            dados_input.append({"cep": c, "numero": n})
            
    # Botão de Execução
    btn_gerar = st.button("🚀 GERAR ROTEIRO", use_container_width=True, type="primary")
    
    # BOTÃO DE LIMPAR (Lógica de Reset Total)
    if st.button("🗑️ LIMPAR TUDO", use_container_width=True):
        for key in list(st.session_state.keys()):
            if "input_" in key or "v150" in key:
                del st.session_state[key]
        st.rerun() # Força o app a recomeçar do zero

# --- 5. EXECUÇÃO DA ROTA ---
if btn_gerar and dados_input:
    pts_gps = []
    for item in dados_input:
        res = get_coords_cep(item['cep'], item['numero'], ORS_KEY)
        if res: pts_gps.append(res)
    
    if not pts_gps:
        st.error("Nenhum CEP válido encontrado."); st.stop()

    try:
        # Ordenação
        if "Inteligente" in modo:
            lista_pendente = pts_gps.copy()
            ponto_atual = u_base
            pts_ordenados = []
            
            while lista_pendente:
                coords_matriz = [[ponto_atual['lon'], ponto_atual['lat']]] + [[p['lon'], p['lat']] for p in lista_pendente]
                matriz = ors_client.distance_matrix(locations=coords_matriz, profile='driving-car', metrics=['distance'])
                dists = matriz['distances'][0][1:]
                
                idx_proximo = dists.index(min(dists))
                proximo_ponto = lista_pendente.pop(idx_proximo)
                pts_ordenados.append(proximo_ponto)
                ponto_atual = proximo_ponto
        else:
            pts_ordenados = pts_gps

        # Cálculo de Percurso (Trecho a Trecho)
        itinerario = []
        geometria = []
        dist_total = 0
        percurso_final = [u_base] + pts_ordenados + [u_base]
        
        itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Dist": "0.0 km", "lat": u_base['lat'], "lon": u_base['lon']})

        for i in range(len(percurso_final) - 1):
            origem, destino = percurso_final[i], percurso_final[i+1]
            trecho = ors_client.directions(
                coordinates=[[origem['lon'], origem['lat']], [destino['lon'], destino['lat']]],
                profile='driving-car', format='geojson'
            )
            
            d_km = round(trecho['features'][0]['properties']['summary']['distance'] / 1000, 2)
            dist_total += d_km
            geometria.extend([[c[1], c[0]] for c in trecho['features'][0]['geometry']['coordinates']])
            
            label = "Retorno" if i == len(percurso_final) - 2 else f"{i+1}º"
            itinerario.append({
                "Seq": label, "Destino": destino['endereco'], "Dist": f"{d_km} km", 
                "lat": destino['lat'], "lon": destino['lon']
            })

        # Salva o resultado na sessão
        st.session_state.v150 = {"tabela": itinerario, "mapa": geometria, "total": round(dist_total, 2)}

    except Exception as e:
        st.error(f"Erro no cálculo: {e}")

# --- 6. EXIBIÇÃO DOS RESULTADOS ---
if "v150" in st.session_state:
    res = st.session_state.v150
    st.subheader(f"🏁 Percurso Total: {res['total']} km")
    
    col_tab, col_map = st.columns([1, 1.2])
    
    with col_tab:
        # Tabela sem colunas técnicas
        df_view = pd.DataFrame(res['tabela']).drop(columns=['lat', 'lon'])
        st.dataframe(df_view, use_container_width=True, hide_index=True)

        # LINK WHATSAPP (Formato de Coordenadas para Precisão)
        lista_coords = [f"{p['lat']},{p['lon']}" for p in res['tabela']]
        link_google = f"https://www.google.com/maps/dir/?api=1&origin={lista_coords[0]}&destination={lista_coords[-1]}&waypoints={'|'.join(lista_coords[1:-1])}&travelmode=driving"
        
        msg_wpp = f"🚚 *ROTEIRO TECNOLAB*\nTotal: {res['total']} km\n\n"
        for p in res['tabela']:
            icon = "🏢" if p['Seq'] in ['Saída', 'Retorno'] else "📍"
            msg_wpp += f"{icon} *{p['Seq']}*: {p['Destino']}\n"
        msg_wpp += f"\n🚀 *GPS:* {link_google}"
        
        st.link_button("🟢 ENVIAR WHATSAPP", f"https://api.whatsapp.com/send?text={urllib.parse.quote(msg_wpp)}", use_container_width=True)

    with col_map:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        folium.PolyLine(res['mapa'], color="blue", weight=5, opacity=0.7).add_to(m)
        
        # Marcadores com proteção contra sobreposição
        coords_memo = {}
        for p in res['tabela']:
            lat, lon = p['lat'], p['lon']
            chave = (round(lat, 4), round(lon, 4))
            if chave in coords_memo:
                lat += 0.0001; lon += 0.0001 # Pequeno desvio visual
            coords_memo[chave] = True

            is_base = p['Seq'] in ['Saída', 'Retorno']
            folium.Marker(
                [lat, lon],
                popup=f"<b>{p['Seq']}</b><br>{p['Destino']}",
                tooltip=p['Seq'],
                icon=folium.Icon(color='green' if is_base else 'blue', icon='info-sign')
            ).add_to(m)
        
        st_folium(m, use_container_width=True, height=500)
