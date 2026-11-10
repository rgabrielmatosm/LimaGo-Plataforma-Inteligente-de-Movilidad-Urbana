"""Pruebas de integración: API + worker + persistencia (SQLite) sobre la malla sintética."""
from tests.conftest import LAT0, LON0, PASO, nodo_malla


def test_flujo_completo_solicitud_seguimiento_historial(entorno_api, malla):
    cliente, trabajador = entorno_api
    assert cliente.get("/api/salud").json()["worker_activo"] is True
    flota = cliente.get("/api/flota").json()
    assert len(flota["conductores"]) == 10 and flota["en_pausa"] is True
    destino = malla.coordenadas(nodo_malla(0, 0))
    r = cliente.post("/api/viajes", json={"origen": {"texto": "Plaza Central"},
                                          "destino": {"lat": destino[0], "lon": destino[1]}})
    assert r.status_code == 201, r.text
    viaje = r.json()
    assert viaje["estado"] == "asignada" and viaje["conductor"]["estado"] == "en_camino"
    assert len(viaje["candidatos"]) == 3 and viaje["ruta_recogida"]
    # el conductor asignado ya no está disponible en la instantánea publicada por el worker
    flota = cliente.get("/api/flota").json()
    asignado = next(c for c in flota["conductores"] if c["id"] == viaje["conductor_id"])
    assert asignado["estado"] == "en_camino"
    # avanzar turnos hasta completar
    for _ in range(40):
        cliente.post("/api/operaciones/avanzar", json={"turnos": 5})
        if cliente.get(f"/api/viajes/{viaje['id']}").json()["estado"] == "completada":
            break
    assert cliente.get(f"/api/viajes/{viaje['id']}").json()["estado"] == "completada"
    historial = cliente.get("/api/viajes").json()["solicitudes"]
    assert historial[0]["id"] == viaje["id"]
    trabajador.simulador.despachador.verificar_consistencia()


def test_errores_de_ubicacion_y_controles(entorno_api):
    cliente, _ = entorno_api
    r = cliente.post("/api/viajes", json={"origen": {"texto": "Lugar que no existe"}})
    assert r.status_code == 422 and r.json()["codigo"] == "direccion_no_encontrada"
    r = cliente.post("/api/viajes", json={"origen": {"lat": -12.0464, "lon": -77.0428}})
    assert r.status_code == 422 and r.json()["codigo"] == "fuera_de_cobertura"
    r = cliente.post("/api/viajes", json={"origen": {"lat": LAT0 + 2.5 * PASO, "lon": LON0 + 2.5 * PASO}})
    assert r.status_code == 422 and r.json()["codigo"] == "sin_conexion_vial"
    assert cliente.post("/api/viajes", json={"origen": {"lat": 200, "lon": 0}}).status_code == 422
    assert cliente.get("/api/viajes").json()["solicitudes"][0]["estado"] == "rechazada"
    assert cliente.post("/api/operaciones/reanudar").json()["en_pausa"] is False
    assert cliente.post("/api/operaciones/pausar").json()["en_pausa"] is True
    turno = cliente.post("/api/operaciones/avanzar", json={"turnos": 3}).json()["turno"]
    assert turno >= 3
    reinicio = cliente.post("/api/operaciones/reiniciar", json={"semilla": 5, "num_conductores": 6}).json()
    assert reinicio["turno"] == 0 and reinicio["semilla"] == 5
    assert len(cliente.get("/api/flota").json()["conductores"]) == 6
    assert cliente.post("/api/operaciones/borrar-todo").status_code == 404


def test_cancelacion_y_lote(entorno_api, malla):
    cliente, _ = entorno_api
    lat, lon = malla.coordenadas(nodo_malla(4, 4))
    viaje = cliente.post("/api/viajes", json={"origen": {"lat": lat, "lon": lon}}).json()
    cancelado = cliente.post(f"/api/viajes/{viaje['id']}/cancelar").json()
    assert cancelado["estado"] == "cancelada"
    assert cliente.post(f"/api/viajes/{viaje['id']}/cancelar").status_code == 409
    puntos = [dict(zip(("lat", "lon"), malla.coordenadas(n))) for n in (nodo_malla(0, 1), nodo_malla(5, 4), nodo_malla(3, 0))]
    lote = cliente.post("/api/viajes/lote", json={"pasajeros": puntos}).json()
    assert len(lote["solicitudes"]) == 3
    assert lote["espera_total_s"] <= lote["espera_total_alternativa_s"] + 1e-6
    ids = [a["conductor_id"] for a in lote["asignaciones"]]
    assert len(set(ids)) == 3
