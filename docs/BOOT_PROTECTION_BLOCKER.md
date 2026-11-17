# Bloqueo del arranque: protección del ejecutable — 2026-11-17

## Qué se observó (análisis estático y referencia x86 aislada)

- El punto de entrada del ejecutable inventariado (`0x851370`) está en la sección `.prus`, no en `.text`. En Windows, el código de esa sección se ejecuta antes que el del juego.
- `.prus` (ejecutable y escribible) y `.izbf` están prácticamente vacías en el archivo (entropía 0,12 y 0,01): su contenido real se genera en tiempo de ejecución. Es el patrón de un *wrapper* de protección.
- El código del juego en `.text` llama 37 veces a través de una entrada de tabla situada en `.prus` (`[0x850000]`), en lugar de usar la tabla de importaciones normal. Las otras 343 llamadas a Windows usan `.idata` con normalidad.
- Al recorrer los inicializadores estáticos en orden, el décimo primero (`0x455ff0`) llega a esa entrada a través de la gestión de datos por hilo de la CRT (`0x612eb0`). Ahí la ejecución entraría en el código de la protección.

## Política

`AGENTS.md`: **no eludir protecciones**. Por tanto, el port **no** ejecuta, emula, rellena, reconstruye ni sustituye el código o las tablas de `.prus`/`.izbf`, y tampoco intenta deducir qué hay detrás de la entrada redirigida. `tools/trace_static_init_x86.py` se detiene explícitamente si la ejecución entra en esas secciones, y en el código traducido cualquier llamada allí acaba en un fallo de despacho controlado.

## Consecuencias

- La fase 1 (86 inicializadores verificados en el S25) usa solo código del propio juego y no pasa por la protección.
- El arranque completo **no puede avanzar con este ejecutable** sin cruzar esa frontera: el inicializador `0x455ff0` y los posteriores que dependen de los datos por hilo de la CRT, y el propio punto de entrada.
- El trabajo que no depende del arranque sigue siendo posible: traducción verificada de subsistemas aislados (gráficos, entrada, sonido, lógica), capa de API de Windows y renderizador.

## Camino legítimo

Para continuar el arranque haría falta un ejecutable oficial del juego que no lleve este *wrapper* y que el propietario posea legítimamente. Habría que inventariarlo y verificarlo igual que el actual. Este documento no describe ni propone ningún método para retirar o sortear la protección.
