# --- 5. LÓGICA DE CÁLCULO (VERSÃO CORRIGIDA V11.3) ---
if btn and ceps:
    with st.spinner("Sincronizando distâncias reais..."):
        pts_gps = []
        for c in ceps:
            res = get_coords_cep(c, ors_client)
            if res: pts_gps.append(res)
        
        if not pts_gps:
            st.error("Nenhum CEP válido encontrado."); st.stop()

        try:
            # 1. Definir a ordem de chamada das coordenadas
            # Sempre: [MATRIZ, PONTOS..., MATRIZ]
            coords_chamada = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps] + [[u_base['lon'], u_base['lat']]]
            
            otimizar = (modo == "Otimizar Caminho (IA)")
            res_api = ors_client.directions(
                coordinates=coords_chamada, 
                profile='driving-car', 
                format='geojson', 
                optimize_waypoints=otimizar
            )

            # 2. SEGREDO: Descobrir a ordem REAL que a API usou
            if otimizar and 'waypoint_order' in res_api['metadata']['query']:
                ordem_ia = res_api['metadata']['query']['waypoint_order']
                # Reorganiza nossa lista de objetos conforme a IA decidiu
                pts_ordenados = [pts_gps[i] for i in ordem_ia]
            else:
                # Mantém a ordem exata da digitação
                pts_ordenados = pts_gps

            # 3. Montar o itinerário garantindo que a distância i é para chegar no ponto i
            itinerario = []
            segs = res_api['features'][0]['properties']['segments']
            
            # Linha da Saída (sempre zero)
            itinerario.append({
                "Seq": "Saída", 
                "Destino": u_base['nome'], 
                "Distancia": "0.0 km", 
                "Tempo": "0 min", 
                "lat": u_base['lat'], "lon": u_base['lon']
            })
            
            # Loop pelos pontos ordenados
            # O segmento[i] é SEMPRE o trajeto para chegar no pts_ordenados[i]
            for i, p in enumerate(pts_ordenados):
                dist_trecho = round(segs[i]['distance'] / 1000, 2)
                tempo_trecho = round(segs[i]['duration'] / 60, 1)
                itinerario.append({
                    "Seq": f"{i+1}º",
                    "Destino": f"{p['endereco']} ({p['cep']})",
                    "Distancia": f"{dist_trecho} km",
                    "Tempo": f"{tempo_trecho} min",
                    "lat": p['lat'], "lon": p['lon']
                })
            
            # Linha do Retorno (o último segmento da lista)
            dist_retorno = round(segs[-1]['distance'] / 1000, 2)
            tempo_retorno = round(segs[-1]['duration'] / 60, 1)
            itinerario.append({
                "Seq": "Retorno", 
                "Destino": u_base['nome'], 
                "Distancia": f"{dist_retorno} km", 
                "Tempo": f"{tempo_retorno} min", 
                "lat": u_base['lat'], "lon": u_base['lon']
            })

            st.session_state.v112 = {
                "tabela": itinerario,
                "mapa": [[c[1], c[0]] for c in res_api['features'][0]['geometry']['coordinates']],
                "total": round(res_api['features'][0]['properties']['summary']['distance']/1000, 2)
            }
        except Exception as e:
            st.error(f"Erro crítico de processamento: {e}")
