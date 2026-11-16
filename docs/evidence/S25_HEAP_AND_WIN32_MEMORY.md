# Heap del juego y primeros shims de memoria Win32 — 2026-11-16

**Heap.** `0x610be0` no es el `malloc` de la CRT de Microsoft, sino un heap propio del juego: 19 funciones y 808 instrucciones. Usa una tabla de 6 clases de tamaño en `0x7e9ee8` (4, 12, 20, 36, 52 y 68 bytes), un descriptor en `.bss` (`0x822268`) y una sección crítica en `0x828120`, y obtiene la memoria con `GlobalAlloc(GMEM_FIXED, n+8)`. La búsqueda en la tabla termina en el primer dword de los datos que siguen, que forman parte de una cadena de depuración. Por eso arnés y referencia cargan los 7 dwords reales, extraídos de tu ejecutable a un header privado (`private/analysis/heap/heap_data.h`). Con la tabla a cero, el bucle leía memoria arbitraria y la prueba no era válida.

**Traducción.** `tools/recomp_lift.py` es un módulo genérico y auditado. Recorre el grafo de llamadas directas desde unas raíces y solo admite estas reescrituras verificadas: llamadas E8 con retorno exacto, llamadas FF 15 a importaciones de una lista permitida, `rep stos` y `rep movs` comprobados. Rechaza punteros crudos, x87, helpers no comprobados y cualquier otra llamada indirecta. `tools/lift_heap.py` lo usa con tres importaciones permitidas.

**Shims Win32** (`runtime/win32_memory.c`, código público):
- `GlobalAlloc`: solo `GMEM_FIXED` y `GMEM_ZEROINIT`. Reserva en orden de direcciones dentro de una región invitada, alinea a 8 bytes y rellena siempre con ceros. Devuelve 0 si se agota el espacio o si recibe otras flags.
- `EnterCriticalSection`/`LeaveCriticalSection`: modelo de un solo hilo sobre los campos documentados (LockCount, RecursionCount, OwningThread). Detecta el bloqueo imposible y la salida de un hilo que no es el dueño.
- 18 comprobaciones unitarias (`tests/test_win32_memory.c`, también en CTest).

**Prueba del heap.** `tests/heap_native.c` (portable) frente a `tools/probe_heap_x86.py`, que emula en Python las mismas tres API. Hay 16 casos de 40 `malloc` de 1 B a 100 KB: 640 reservas correctas y 128 llamadas a `GlobalAlloc`. Se comparan cada puntero, los registros, la pila, la sección crítica, el CRC-32 de toda la `.bss` y el de la memoria entregada por `GlobalAlloc`. **Coinciden en Windows x64 y en el S25 `SM-S938B`**, con limpieza confirmada.

**Pila completa.** El cargador `0x605750` funciona ahora sobre el asignador del juego, que obtiene su arena del heap del juego, y este de `GlobalAlloc`. Son 52 funciones traducidas, sin ningún doble de memoria, sobre los shims de archivo y memoria del port. Los 16 casos coinciden con x86 en el S25. La app ejecuta el cargador, el asignador y el heap validados con resultado **CORRECTO**.

**Límites.** Un solo hilo. No existen `GlobalFree` ni el resto de flags. La reserva real de 64 MiB del pool no se probó (se usa una arena de 32 KiB). El juego sigue sin arrancar.
