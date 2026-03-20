# --- 5. LÓGICA DE PROCESSAMENTO V13.0 (IA TSP + ISOLAMENTO) ---
if btn_calc and ceps_raw:
    with st.spinner("IA calculando a rota matematicamente mais curta..."):
        pts_gps = []
        for c in ceps_raw:
            res = get_coords_cep(c, ors_client)
            if res: pts_gps.append(res)
        
        if not pts_gps:
            st.error("CEP inválido."); st.stop()

        try:
            # FASE 1: DESCOBRIR A ORDEM ÓTIMA (IA REAL)
            # Enviamos todos para a API de 'directions' apenas para ler o 'waypoint_order'
            coords_ia = [[u_base['lon'], u_base['lat']]] + [[p['lon'], p['lat']] for p in pts_gps] + [[u_base['lon'], u_base['lat']]]
            
            if modo == "Otimizar para Menor Caminho":
                # Aqui a API usa matemática avançada para cruzar todos os pontos
                res_ia = ors_client.directions(
                    coordinates=coords_ia,
                    profile='driving-car',
                    optimize_waypoints=True
                )
                ordem_ia = res_ia['metadata']['query']['waypoint_order']
                pts_ordenados = [pts_gps[i] for i in ordem_ia]
            else:
                pts_ordenados = pts_gps

            # FASE 2: CÁLCULO INDIVIDUAL (FIM DA CONTAMINAÇÃO)
            itinerario = []
            geometria_total = []
            km_total = 0
            percurso = [u_base] + pts_ordenados + [u_base]
            
            itinerario.append({"Seq": "Saída", "Destino": u_base['endereco'], "Km Trecho": "0.0", "Tempo": "0", "lat": u_base['lat'], "lon": u_base['lon']})

            for i in range(len(percurso) - 1):
                origem, destino = percurso[i], percurso[i+1]
                
                # Chamada 100% isolada para este trecho
                trecho = ors_client.directions(
                    coordinates=[[origem['lon'], origem['lat']], [destino['lon'], destino['lat']]],
                    profile='driving-car', format='geojson'
                )
                
                d = trecho['features'][0]['properties']['summary']
                d_km = round(d['distance'] / 1000, 2)
                km_total += d_km
                
                geometria_total.extend([[c[1], c[0]] for c in trecho['features'][0]['geometry']['coordinates']])
                
                label = "Retorno" if i == len(percurso) - 2 else f"{i+1}ª Parada"
                itinerario.append({
                    "Seq": label,
                    "Destino": f"{destino['endereco']} ({destino.get('cep', '')})",
                    "Km Trecho": f"{d_km} km",
                    "Tempo": f"{round(d['duration']/60, 1)} min",
                    "lat": destino['lat'], "lon": destino['lon']
                })

            st.session_state.v13 = {"tabela": itinerario, "mapa": geometria_total, "total": round(km_total, 2)}

        except Exception as e:
            st.error(f"Erro na otimização: {e}")
