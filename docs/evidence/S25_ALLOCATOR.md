# Asignador de memoria del juego en ARM64 — 2026-11-16

**Qué es** (deducido del código): un pool en `0x67d000` construido por el inicializador estático `0x401dc0` con `0x4010b0(0x4000000)`. Su arena de 64 MiB la pide al `malloc` del CRT (`0x610be0`). Cada bloque lleva una cabecera de 16 bytes: bloque físico anterior, siguiente y anterior en la lista, y tamaño con dos flags (bit 31 = reservado, bit 30 = en lista pequeña). Hay 128 listas de tamaños pequeños, múltiplos de 16 hasta 2 KiB (zancada de 36 bytes desde `+0x38`), y una lista grande ordenada por tamaño. `0x401350` reserva y `0x401b00` libera, fusionando bloques vecinos. Si `[0x67e264]` está activo, el bloque reservado se rellena con `rep stosb` (`0x401580`).

**Traducción.** `tools/lift_allocator.py` tradujo 12 funciones (450 instrucciones): constructor, reservar, liberar y sus auxiliares. Se validaron 11 llamadas directas con retorno exacto. El `rep stosb`, que PCRecomp traduce como `memset` sobre un puntero crudo, pasa por el nuevo `mh_recomp_rep_stos` del adaptador comprobado. En la prueba coincidió con un modelo x86 elemento a elemento en 2016 casos y rechazó la escritura fuera de rango sin escribir nada. Solo el `malloc` del CRT de la arena es un doble de prueba.

**Prueba.** `tests/allocator_native.c` (portable) y `tools/probe_allocator_x86.py`, que ejecuta el `.text` real en Unicorn. Cada uno de los 16 casos construye el pool sobre una arena de 192 KiB y ejecuta 60 operaciones pseudoaleatorias deterministas de reserva y liberación (de 1 B a 12 KiB, con y sin relleno a cero, cuatro alineaciones de pila). En total son 654 reservas y 306 liberaciones. Se comparan cada puntero devuelto, el objeto pool completo (`0x1268` bytes), la pila, un hash FNV-1a de la arena, los registros y las banderas.

**Resultado:** coinciden los 16 casos y las 960 operaciones en **Windows x64 y en el S25 `SM-S938B`**, con la limpieza confirmada.

**Banderas indefinidas.** Con relleno a cero, una reserva termina con las banderas del `imul` de `0x401580`. Intel solo define CF y OF tras `IMUL`; SF, ZF, AF y PF quedan indefinidas. En esos casos (cuatro de los 16) Unicorn y el C dieron valores distintos de ZF/PF, así que el comparador solo exige CF/OF ahí. Las demás banderas se comparan íntegramente en el resto de casos.

**Integración.** El cargador `0x605750` usa ahora este asignador real en lugar de sus dobles: 33 funciones traducidas trabajando juntas. Sigue coincidiendo con x86 en 16 casos en el S25 (ver `S25_LOADER.md`). La app ejecuta ambos binarios validados con resultado idéntico.

**Límites.** Un solo hilo; no se modelan las secciones críticas del CRT; la arena es pequeña y sintética. No se ha probado la reserva de 64 MiB real.
