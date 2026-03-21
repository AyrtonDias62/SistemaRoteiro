import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V15.0", layout="wide", page_icon="🚚")

# --- 2. FUNÇÃO DE COORDENADAS (VERSÃO COM CERCA GEOGRÁFICA RÍGIDA) ---
@st.cache_data(show_spinner=False)
def get_coords_cep(cep,numero, _ors_client): # Adicionado parâmetro numero
    try:
        # 1. Limpeza e Consulta ViaCEP
        clean_cep = str(cep).replace('-', '').replace(' ', '').strip()
        if len(clean_cep) != 8: return None
        
        r = requests.get(f"https://viacep.com.br/ws/{clean_cep}/json/").json()
        if "erro" in r: return None

        logradouro = r.get('logradouro', '')
        cidade = r.get('localidade', '')
        # Se não tiver rua (CEP geral), busca pela cidade
        # AGORA INCLUÍMOS O NÚMERO NA BUSCA TEXTUAL
        texto_busca = f"{logradouro}, {numero}, {cidade}" if logradouro else f"{cidade}, SP"

        # 2. Chamada Direta via API (Ignora limitações da biblioteca Python)
        # Usamos o boundary.circle para travar no ABCD + Grande SP
        url = "https://api.openrouteservice.org/geocode/search"
        params = {
            'api_key': st.secrets["ORS_KEY"],
            'text': texto_busca,
            'size': 1,
            'boundary.circle.lat': -23.6912,  # Latitude da Matriz SBC
            'boundary.circle.lon': -46.5594,  # Longitude da Matriz SBC
            'boundary.circle.radius': 50,     # Raio de 50km (Cobre todo ABCD/SP)
            'layers': 'address,venue,street'  # Foca em endereços reais
        }

        response = requests.get(url, params=params)
        if response.status_code != 200: return None
        
        geo = response.json()
        
        if geo and len(geo['features']) > 0:
            coords = geo['features'][0]['geometry']['coordinates']
            return {
                "lat": coords[1], 
                "lon": coords[0], 
                "endereco": f"{logradouro}, {numero} - {cidade}", 
                "cep": clean_cep
            }
        
        # Fallback: Se não achou com a rua, tenta apenas o CEP bruto dentro do círculo
        params['text'] = f"{clean_cep}, Brasil"
        response_retry = requests.get(url, params=params)
        geo_retry = response_retry.json()
        
        if geo_retry and len(geo_retry['features']) > 0:
            coords = geo_retry['features'][0]['geometry']['coordinates']
            return {
                "lat": coords[1], "lon": coords[0], 
                "endereco": f"CEP {clean_cep}, {cidade}", "cep": clean_cep
            }

        return None
    except Exception as e:
        st.error(f"Erro ao processar CEP {cep}: {e}")
        return None

# --- 3. SETUP API ---
try:
    ors_client = client.Client(key=st.secrets["ORS_KEY"])
except:
    st.error("Erro na ORS_KEY."); st.stop()

u_base = {"endereco": "Tecno Matriz SBC", "lat": -23.6912, "lon": -46.5594, "cep": "Matriz"}

# --- 4. INTERFACE (COM NÚMERO) ---
with st.sidebar:
    st.header("🚚 Roteirizador Tecnolab")
    modo = st.selectbox("Comportamento do Roteiro:", [
        "1. Roteiro Ordenado (Ordem do Input)", 
        "2. Roteiro Inteligente (Circular/Otimizado)"
    ])
    st.divider()
    
    dados_input = []
    for i in range(5):
        col_cep, col_num = st.columns([2, 1])
        with col_cep:
            c = st.text_input(f"CEP {i+1}", key=f"cep_{i}")
        with col_num:
            n = st.text_input(f"Nº", key=f"num_{i}")
        
        if c: 
            dados_input.append({"cep": c, "numero": n})
            
    btn = st.button("🚀 GERAR ROTEIRO", use_container_width=True, type="primary")

# --- 5. EXECUÇÃO ---
if btn and dados_input:
    pts_gps = []
    for item in dados_input:
        # Passando CEP e Número para a função
        res = get_coords_cep(item['cep'], item['numero'], ors_client)
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

# --- 6. EXIBIÇÃO (VERSÃO COM COORDENADAS REAIS NO GOOGLE MAPS) ---
if "v143" in st.session_state:
    r = st.session_state.v143
    st.subheader(f"🏁 Total do Percurso: {r['total']} km")
    
    col1, col2 = st.columns([1, 1.2])
    
    with col1:
        # Tabela de endereços
        df_exibicao = pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon'])
        st.dataframe(df_exibicao, use_container_width=True, hide_index=True)

        # --- LÓGICA DO WHATSAPP COM COORDENADAS ---
        import urllib.parse
        
        # 1. Gerar Link do Google Maps usando LAT,LON para evitar erros de endereço
        # Formato: https://www.google.com/maps/dir/lat,lon/lat,lon/lat,lon...
        lista_coords = [f"{p['lat']},{p['lon']}" for p in r['tabela']]
        link_google = f"https://www.google.com/maps/dir/{'/'.join(lista_coords)}"

        # 2. Montar texto formatado para o WhatsApp
        texto_wpp = f"🚚 *ROTEIRO TECNOLAB*\n"
        texto_wpp += f"Total: {r['total']} km\n\n"
        for p in r['tabela']:
            # Se for a Saída ou Retorno, usamos um emoji diferente
            icon = "🏢" if p['Seq'] in ['Saída', 'Retorno'] else "📍"
            texto_wpp += f"{icon} *{p['Seq']}*: {p['Destino']}\n"
        
        texto_wpp += f"\n👉 *INICIAR NAVEGAÇÃO (GPS):*\n{link_google}"
        
        msg_encoded = urllib.parse.quote(texto_wpp)
        link_final_wpp = f"https://api.whatsapp.com/send?text={msg_encoded}"

        st.divider()
        st.link_button("🟢 ENVIAR PARA WHATSAPP", link_final_wpp, use_container_width=True, type="primary")

    with col2:
        # MAPA FOLIUM
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        cor_linha = "red" if "Inteligente" in modo else "blue"
        
        folium.PolyLine(r['mapa'], color=cor_linha, weight=5, opacity=0.8).add_to(m)
        
        for p in r['tabela']:
            is_base = p['Seq'] in ['Saída', 'Retorno']
            folium.Marker(
                [p['lat'], p['lon']], 
                tooltip=p['Destino'],
                icon=folium.Icon(color='green' if is_base else 'blue', icon='info-sign')
            ).add_to(m)
        
        st_folium(m, use_container_width=True, height=500)
