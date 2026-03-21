import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V14.4", layout="wide", page_icon="🚚")

# --- 2. FUNÇÃO DE COORDENADAS (VERSÃO COM CERCA GEOGRÁFICA RÍGIDA) ---
@st.cache_data(show_spinner=False)
def get_coords_cep(cep, _ors_client):
    try:
        # 1. Limpeza e Consulta ViaCEP
        clean_cep = str(cep).replace('-', '').replace(' ', '').strip()
        r = requests.get(f"https://viacep.com.br/ws/{clean_cep}/json/").json()
        if "erro" in r: return None

        logradouro = r.get('logradouro', '')
        cidade = r.get('localidade', '')
        
        # 2. Configuração do Círculo de Segurança (ABCD + SP)
        # Centro: Sua Matriz em SBC (-23.6912, -46.5594)
        # Raio: 50km (cobre todo o ABCDMRR e capital)
        ponto_central = [-46.5594, -23.6912] 
        raio_km = 50 

        # 3. Funil de Busca
        # Removendo argumentos nomeados problemáticos e usando a estrutura de filtros
        tentativas = [
            f"{logradouro}, {cidade}, SP",
            f"{clean_cep}, Brasil"
        ]

        for texto in tentativas:
            # Buscamos usando boundary_circle que é amplamente suportado
            geo = _ors_client.pelias_search(
                text=texto,
                size=1,
                boundary_circle={
                    "centre": ponto_central,
                    "radius": raio_km
                }
            )
            
            if geo and len(geo['features']) > 0:
                coords = geo['features'][0]['geometry']['coordinates']
                return {
                    "lat": coords[1], 
                    "lon": coords[0], 
                    "endereco": f"{logradouro or 'CEP '+clean_cep}, {cidade}", 
                    "cep": clean_cep
                }
        
        return None
    except Exception as e:
        st.error(f"Erro técnico no CEP {cep}: {e}")
        return None

# --- 3. SETUP API ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro na ORS_KEY."); st.stop()

u_base = {"endereco": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594, "cep": "Matriz"}

# --- 4. INTERFACE ---
with st.sidebar:
    st.header("🚚 Sistema Tecnolab")
    modo = st.selectbox("Comportamento do Roteiro:", [
        "1. Roteiro Travado (Ordem do Input)", 
        "2. Roteiro Inteligente (Circular/Otimizado)"
    ])
    st.divider()
    ceps_raw = []
    for i in range(5):
        c = st.text_input(f"CEP {i+1}", key=f"cep_v143_{i}")
        if c: ceps_raw.append(c)
    btn = st.button("🚀 GERAR ROTEIRO", use_container_width=True, type="primary")

# --- 5. EXECUÇÃO ---
if btn and ceps_raw:
    pts_gps = []
    for c in ceps_raw:
        res = get_coords_cep(c, ors_client)
        if res: pts_gps.append(res)
    
    if not pts_gps:
        st.error("Nenhum CEP encontrado."); st.stop()

    try:
        pts_ordenados = []
        
        # --- LÓGICA MODO 2: INTELIGENTE (ORDENAÇÃO POR PROXIMIDADE) ---
        if "Inteligente" in modo:
            # Criamos uma lista de trabalho começando pela base
            lista_pendente = pts_gps.copy()
            ponto_atual = u_base
            pts_ordenados = []
            
            # Algoritmo do "Vizinho Mais Próximo" (Garante o caminho circular)
            while lista_pendente:
                proximo_ponto = None
                menor_distancia = float('inf')
                idx_proximo = 0
                
                # Comparamos o ponto atual com todos os que faltam visitar
                coords_matriz = [[ponto_atual['lon'], ponto_atual['lat']]] + [[p['lon'], p['lat']] for p in lista_pendente]
                matriz = ors_client.distance_matrix(locations=coords_matriz, profile='driving-car', metrics=['distance'])
                
                # Pegamos as distâncias do ponto atual (índice 0) para os outros
                dists = matriz['distances'][0][1:]
                
                for i, d in enumerate(dists):
                    if d < menor_distancia:
                        menor_distancia = d
                        proximo_ponto = lista_pendente[i]
                        idx_proximo = i
                
                pts_ordenados.append(proximo_ponto)
                ponto_atual = proximo_ponto
                lista_pendente.pop(idx_proximo)
        
        # --- LÓGICA MODO 1: TRAVADO ---
        else:
            pts_ordenados = pts_gps

        # --- CÁLCULO FINAL (IGUAL PARA AMBOS, MAS COM ORDENS DIFERENTES) ---
        itinerario = []
        geometria = []
        dist_total = 0
        percurso_final = [u_base] + pts_ordenados + [u_base]
        
        # Adiciona a Saída
        itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Dist": "0.0 km", "lat": u_base['lat'], "lon": u_base['lon']})

        # Calcula trecho a trecho (Garante KMs reais e isolamento do retorno)
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
                "Seq": label, 
                "Destino": destino['endereco'], 
                "Dist": f"{d_km} km", 
                "lat": destino['lat'], "lon": destino['lon']
            })

        st.session_state.v143 = {"tabela": itinerario, "mapa": geometria, "total": round(dist_total, 2)}

    except Exception as e:
        st.error(f"Erro: {e}")

# --- 6. EXIBIÇÃO ---
if "v143" in st.session_state:
    r = st.session_state.v143
    st.subheader(f"🏁 Total do Percurso: {r['total']} km")
    
    col1, col2 = st.columns([1, 1.2])
    with col1:
        st.dataframe(pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon']), use_container_width=True, hide_index=True)
    
    with col2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        cor_linha = "red" if "Inteligente" in modo else "blue"
        folium.PolyLine(r['mapa'], color=cor_linha, weight=5, opacity=0.8).add_to(m)
        
        for p in r['tabela']:
            is_base = p['Seq'] in ['Saída', 'Retorno']
            folium.Marker(
                [p['lat'], p['lon']], 
                tooltip=p['Seq'],
                icon=folium.Icon(color='green' if is_base else 'blue')
            ).add_to(m)
        st_folium(m, use_container_width=True, height=500)
