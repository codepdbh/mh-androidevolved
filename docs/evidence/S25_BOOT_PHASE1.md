# Arranque, fase 1: inicializadores estáticos en ARM64 — 2026-11-17

**Qué es.** Antes de `WinMain`, el runtime de C++ ejecuta los 98 inicializadores listados en `.CRT`. Construyen objetos globales, registran destructores y crean el pool de memoria. `tools/inspect_static_initializers.py` los clasifica (resumen público en `analysis/static_initializers.md`).

**Cargar el ejecutable como lo haría Windows.** El arnés lee tu `manhunt.exe` (en el S25, la copia verificada de `/sdcard/mh-androidevolved`) y comprueba su tamaño y su CRC-32. Después lo mapea en memoria invitada con `runtime/pe32_image.c`, en la base `0x400000`: cabeceras y secciones en sus RVA. Esta es la primera vez que el código traducido corre sobre la imagen real del juego, no sobre memoria sintética.

**Traducción** (`tools/lift_static_init.py`, con el módulo `tools/recomp_lift.py` ampliado):
- **86 inicializadores** en orden de `.CRT`, con un cierre de 417 funciones y 10 130 instrucciones.
- **Llamadas indirectas:** 26 sitios, sobre todo el iterador de constructores de arrays de C++. Pasan por una tabla de despacho generada que falla de forma controlada ante cualquier destino no traducido. Las funciones pasadas como punteros (143) se incluyen en el cierre.
- **CPU virtual** (`recomp/virtual_cpu.h`): PCRecomp pregunta a la CPU del host con MSVC y no hace nada en Android, donde los registros quedarían con valores antiguos. El port responde siempre con una CPU fija: «GenuineIntel», familia 6, solo FPU, sin MMX/CMOV/SSE. Así el juego elige sus rutas x87/enteras.
- **Lista blanca cerrada de macros.** PCRecomp implementa `CMP_O`/`CMP_NO`/`CMP_P`/`CMP_NP` (saltos `jo`/`jno`/`jp`/`jnp`) como `TODO` con resultado constante; quedan excluidos a propósito.
- **Paradas automáticas:** las funciones que no superan la auditoría (aquí 3: una con x87, una con salto indirecto de cola y una que llama a `GlobalFree`) quedan como *stubs* que fallan de forma controlada.
- **Shims de memoria:** los de `runtime/win32_memory.c`. El pool hace una reserva real de 64 MiB con `GlobalAlloc`.

**Resultado.** La referencia (`tools/probe_static_init_x86.py`) ejecuta el `.text` real en Unicorn, mapeado igual, con la misma CPU virtual y los mismos shims. **Coinciden en Windows x64 y en el S25 `SM-S938B`**:
- los registros devueltos por los 86 inicializadores;
- los CRC-32 de `.data`, `.bss`, la imagen completa (6 MiB), la zona de pila y los 64 MiB del pool;
- las llamadas a la API.

La limpieza se confirmó. Durante la verificación se corrigió la referencia: debía arrancar con EFLAGS.IF = 1, como cualquier proceso en modo usuario.

**Límites.** Quedan 12 inicializadores pendientes, con x87, salto de cola o API todavía no implementadas (`GlobalFree`, `TlsGetValue`/`TlsSetValue`, `MessageBoxA`, `ExitProcess`, `CreateEventA`, `CreateFileA`, `GetTickCount`). Se supone que la CRT ya inicializó la sección crítica del heap. No se ejecuta `WinMain`, y el juego sigue sin arrancar.
