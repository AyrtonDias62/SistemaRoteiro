import streamlit as st
import pandas as pd
import requests
import openrouteservice
from openrouteservice import client
import folium
from streamlit_folium import st_folium

# --- 1. CONFIGURAÇÃO ---
st.set_page_config(page_title="Roteirizador Tecnolab V15.4", layout="wide", page_icon="🚚")

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
        bairro = r.get('bairro', '')
        # Se não tiver rua (CEP geral), busca pela cidade
        # AGORA INCLUÍMOS O NÚMERO NA BUSCA TEXTUAL
        texto_busca = f"{logradouro}, {numero}, {bairro}, {cidade}" if logradouro else f"{cidade}, SP"

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
            'layers': 'address',  # Foca em endereços reais
            'sources': 'openstreetmap,openaddresses' # Fontes mais precisas para números
        }

        response = requests.get(url, params=params)
        if response.status_code != 200: return None
        
        geo = response.json()
        
        if geo and len(geo['features']) > 0:
            feat = geo['features'][0]
            coords = feat['geometry']['coordinates']
            
            # Validação Extra: Se o nome retornado for MUITO diferente do esperado (ex: Columbia vs Coimbra)
            # o OpenRouteService costuma retornar o nome encontrado em 'properties']['name']
            nome_encontrado = feat['properties'].get('name', '').lower()
            
            # Se ele "viajou" para outra rua, tentamos uma busca apenas pelo CEP como último recurso
            if logradouro.lower() not in nome_encontrado and "columbia" in logradouro.lower():
                 params['text'] = f"{clean_cep}, Brasil"
                 res_cep = requests.get(url, params=params).json()
                 if res_cep['features']:
                     coords = res_cep['features'][0]['geometry']['coordinates']
            
            return {
                "lat": coords[1], 
                "lon": coords[0], 
                "endereco": f"{logradouro}, {numero} - {bairro} - {cidade}",
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
# --- 4. INTERFACE (ATUALIZADA COM BOTÃO LIMPAR) ---
# --- 4. INTERFACE (ORGANIZADA) ---
with st.sidebar:
    st.header("🚚 Sistema Tecnolab")
    modo = st.selectbox("Comportamento do Roteiro:", [
        "1. Roteiro Travado (Ordem do Input)", 
        "2. Roteiro Inteligente (Circular/Otimizado)"
    ])
    st.divider()
    
    dados_input = []
    for i in range(5):
        col_cep, col_num = st.columns([2, 1])
        with col_cep:
            # Importante: o prefixo 'input_' ajuda o botão limpar a identificar o que apagar
            c = st.text_input(f"CEP {i+1}", key=f"input_cep_{i}")
        with col_num:
            n = st.text_input(f"Nº", key=f"input_num_{i}")
        
        if c: 
            dados_input.append({"cep": c, "numero": n})
            
    # Botão de Gerar
    btn = st.button("🚀 GERAR ROTEIRO", use_container_width=True, type="primary")
    
    # Botão de Limpar logo abaixo
    if st.button("🗑️ LIMPAR CAMPOS", use_container_width=True):
        # Remove todas as chaves de entrada e o resultado do roteiro do estado da sessão
        for key in list(st.session_state.keys()):
            if "input_" in key or "v143" in key:
                del st.session_state[key]
        st.rerun() # Recarrega a página do zero

    st.divider()

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

# --- 6. EXIBIÇÃO (VERSÃO FINAL: SEM SOBREPOSIÇÃO + POP-UPS NUMERADOS) ---
if "v143" in st.session_state:
    r = st.session_state.v143
    st.subheader(f"🏁 Total do Percurso: {r['total']} km")
    
    col1, col2 = st.columns([1, 1.2])
    
    with col1:
        df_exibicao = pd.DataFrame(r['tabela']).drop(columns=['lat', 'lon'])
        st.dataframe(df_exibicao, use_container_width=True, hide_index=True)

        # --- WHATSAPP COM LINK DE PRECISÃO ---
        import urllib.parse
        
        # Geramos o link de navegação forçando as coordenadas
        # O parâmetro 'origin' e 'destination' com lat,lon evita que o Google busque nomes de empresas
        lista_coords = [f"{p['lat']},{p['lon']}" for p in r['tabela']]
        origem = lista_coords[0]
        destino = lista_coords[-1]
        waypoints = "|".join(lista_coords[1:-1])
        
        # Link que força o Google a não "reinterpretar" os nomes
        link_google = f"https://www.google.com/maps/dir/?api=1&origin={origem}&destination={destino}&waypoints={waypoints}&travelmode=driving"

        texto_wpp = f"🚚 *ROTEIRO TECNOLAB*\nTotal: {r['total']} km\n\n"
        for p in r['tabela']:
            icon = "🏢" if p['Seq'] in ['Saída', 'Retorno'] else "📍"
            texto_wpp += f"{icon} *{p['Seq']}*: {p['Destino']}\n"
        
        texto_wpp += f"\n🚀 *INICIAR NO GOOGLE MAPS:*\n{link_google}"
        
        link_final_wpp = f"https://api.whatsapp.com/send?text={urllib.parse.quote(texto_wpp)}"
        st.divider()
        st.link_button("🟢 ENVIAR PARA WHATSAPP", link_final_wpp, use_container_width=True, type="primary")

    with col2:
        m = folium.Map(location=[u_base['lat'], u_base['lon']], zoom_start=12)
        cor_linha = "red" if "Inteligente" in modo else "blue"
        folium.PolyLine(r['mapa'], color=cor_linha, weight=5, opacity=0.8).add_to(m)
        
        # Dicionário para rastrear coordenadas já usadas e evitar sobreposição
        coords_usadas = {}

        for p in r['tabela']:
            lat, lon = p['lat'], p['lon']
            
            # Lógica para evitar que um marcador suma embaixo do outro (mesma rua/número)
            pos_chave = (round(lat, 5), round(lon, 5))
            if pos_chave in coords_usadas:
                coords_usadas[pos_chave] += 1
                # Desloca levemente o marcador (0.0001 aprox 10 metros)
                lat += 0.0001 * coords_usadas[pos_chave]
                lon += 0.0001 * coords_usadas[pos_chave]
            else:
                coords_usadas[pos_chave] = 0

            is_base = p['Seq'] in ['Saída', 'Retorno']
            
            # Pop-up formatado com a Ordem e o Endereço
            conteudo_popup = f"<b>{p['Seq']}</b><br>{p['Destino']}"
            
            folium.Marker(
                [lat, lon], 
                popup=folium.Popup(conteudo_popup, max_width=300),
                tooltip=f"{p['Seq']} - Clique para detalhes",
                icon=folium.Icon(color='green' if is_base else 'blue', 
                                 icon='play' if p['Seq'] == 'Saída' else 'info-sign')
            ).add_to(m)
        
        st_folium(m, use_container_width=True, height=500)
