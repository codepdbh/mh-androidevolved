# Estado vigente — 27 de noviembre de 2026

El port ejecuta el arranque, el menú, las cinemáticas del motor y el primer nivel como código traducido en el Galaxy S25 Ultra. En la partida va a 65–74 fps, con HUD, efecto de cámara, niebla, sombras y luces. Los vídeos Bink todavía no se decodifican. La cobertura está limitada a las rutas traducidas: una sesión libre todavía puede alcanzar una función pendiente y detenerse (la parada es controlada).

## Implementación

- **Traducción**: 11395 funciones, compiladas en 8 partes. Son todas las alcanzables desde el código ejecutado, las tablas de datos y los inmediatos de código.
- **Memoria del código traducido**: la comprobación de rango de cada acceso es inline y los accesos no son `volatile`. `MH_RECOMP_VOLATILE_MEMORY` restaura los accesos `volatile` del original.
- **x87**: el redondeo a 24 bits, la precisión que fija Direct3D, se hace con una conversión a `float` en el rango normal. Fuera de ese rango se usa `frexp`/`ldexp`.
- **Direct3D 8 → OpenGL ES 3**:
  - Los triángulos 3D se dibujan con los buffers del juego, guardados en la GPU según su versión de contenido. La transformación y la iluminación fija (luces puntuales, direccionales y de foco) están en el shader de vértices.
  - Etapas de textura 0 y 1 con las operaciones habituales, generación de coordenadas en espacio de cámara y matrices de textura.
  - Niebla de tabla y de vértice, render targets y culling por GL.
  - Lo pretransformado (HUD, superposiciones) va por CPU y en lotes:
    - La z se limita a [0,1], porque Direct3D no recorta esos vértices.
    - En render targets se ajustan los bordes de píxel, para cubrir lo mismo a cualquier escala.
    - Las líneas y los puntos pretransformados se dibujan como quads de 1 píxel; así salen las líneas de la cámara.
- **Audio**: Miles (IMA ADPCM con tablas exactas), mezclador y AAudio.
- **Entrada y guardado**: controles táctiles; partidas guardadas en el almacenamiento privado de la app, separadas de los datos originales.
- **Reloj**: virtual (determinista), o en tiempo real desde el launcher (opción experimental fuera de los recorridos validados).
- **Diagnóstico** (`adb shell setprop`):
  - `debug.mh.skip`: omite categorías de dibujos.
  - `debug.mh.log`: registra cada dibujo de un fotograma.
  - `debug.mh.dump`: vuelca los render targets a PPM.
  - El registro `perf` desglosa el tiempo de dibujo.

## Compilación y pruebas

- 27-11: los cambios de memoria inline/no-`volatile`, la caché de objetos COM, x87 y ADPCM se validaron dos veces. En cada ciclo, 18 escenarios dieron resultados idénticos a x86 en Windows x64 y en el S25.
- 27-11, S25, primer nivel: 65–74 fps. Por fotograma: ~12 ms de código traducido y ~1,5 ms de dibujo. El 26-11 eran 22–43 fps, con 15–19 ms de código y 9–27 ms de dibujo.
- 27-11, perfil con simpleperf antes de estas optimizaciones:
  - 21 % de la CPU en la decodificación ADPCM;
  - 13 % en la búsqueda lineal de objetos COM;
  - 10 % en `frexp`/`ldexp` del redondeo x87;
  - el resto, código del juego.
- 27-11: prueba de estabilidad en el S25 caminando, corriendo, girando la cámara, atacando y usando objetos. 30 rondas sin caídas; la prueba larga de 90 rondas se documenta en `STATUS.md`.
- 26-11: HUD, efecto de cámara y sombra corregidos y comprobados en el S25 con capturas, guardadas en `private/` porque contienen imágenes del juego.

## Pendiente

- **Vídeos Bink** (21 archivos Bink 1, 512×512, con audio): hoy se reproducen en negro y en silencio durante su duración real. Hace falta un decodificador de vídeo y audio Bink 1.
- La iluminación y las sombras siguen pendientes de comparar con el juego original en PC, que no se ejecuta en este equipo por las reglas del proyecto.
- Sesiones largas fuera del primer nivel: pueden aparecer funciones no traducidas o efectos sin implementar (ver `KNOWN_ISSUES.md`).

## Reglas y límites

- El modo de trabajo seguro permanece activo: procesos supervisados por `scripts/worksafe.py`, límites de recursos y ninguna ejecución nativa del juego original ni de herramientas gráficas en el PC.
- Los archivos originales no se modifican.
- Código traducido, bibliotecas, APK y capturas con contenido del juego permanecen privados.
- El historial técnico anterior está en `STATUS.md`.
