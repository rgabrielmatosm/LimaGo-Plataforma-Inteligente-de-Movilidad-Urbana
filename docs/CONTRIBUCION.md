# Trabajo en equipo y registro de contribuciones

La rúbrica evalúa **commits de todos los integrantes** y la sustentación es **individual**: cada persona debe poder explicar y modificar cualquier parte. Este documento propone cómo trabajar para que el historial de Git refleje las contribuciones reales.

> Importante: no se deben fabricar commits a nombre de otra persona. Cada integrante hace sus commits desde su propia cuenta de GitHub, con su nombre y correo configurados.

## 1. Configuración inicial (cada integrante, una vez)

```powershell
git config --global user.name "Nombre Apellido"
```

```powershell
git config --global user.email "correo-de-su-cuenta-github@ejemplo.com"
```

El dueño del repositorio agrega a los demás en *Settings → Collaborators*.

## 2. Ramas

- `main`: siempre estable (las pruebas pasan).
- Una rama por tarea: `feature/<tema>`, `fix/<tema>`, `docs/<tema>`.

```powershell
git switch main
```

```powershell
git pull
```

```powershell
git switch -c feature/buscar-en-radio
```

Trabajar, ejecutar `python -m pytest -q` y luego:

```powershell
git add estructuras/quadtree.py tests/test_quadtree.py
```

```powershell
git commit -m "Agrega búsqueda por radio en el Quadtree con su prueba"
```

```powershell
git push -u origin feature/buscar-en-radio
```

Abrir un *Pull Request* hacia `main`; **otro integrante lo revisa** (deja comentarios o aprueba) antes de fusionar. La revisión cruzada ayuda a que todos conozcan todo el código.

## 3. Mensajes de commit

En español, en imperativo y describiendo el cambio: «Corrige la fusión de nodos al eliminar», «Documenta la tolerancia del benchmark». Commits pequeños y frecuentes son mejores que uno gigante.

## 4. Reparto sugerido de responsables (rotar la revisión)

| Área | Archivos | Responsable | Revisor |
|---|---|---|---|
| Quadtree y Haversine | `estructuras/` | | |
| Dijkstra, A* y grafo | `algoritmos/grafo.py`, `dijkstra.py`, `a_estrella.py` | | |
| Despachador, flota y turnos | `simulacion/` | | |
| Benchmarks, informe y retos | `benchmark/`, `algoritmos/congestion.py`, `asignacion_multiple.py`, `experimental/` | | |
| API, frontend y Docker | `api/`, `frontend/`, `docker/`, `compose.yaml` | | |

Completen la tabla con sus nombres. Ser responsable no exime de entender el resto: antes de la sustentación cada integrante debe practicar al menos un ejercicio de modificación de cada área (ver `presentacion/index.html`, diapositiva «Ejercicios preparados»).

## 5. Cómo verificar las contribuciones

```powershell
git shortlog -sne
```

```powershell
git log --author="Nombre" --stat
```

## 6. Uso de asistentes de IA

La guía lo permite siempre que el equipo pueda explicar, defender y modificar cada línea. Recomendación: cuando usen un asistente, revisen el código, ejecuten las pruebas y anoten en el Pull Request qué entendieron y qué cambiaron.
