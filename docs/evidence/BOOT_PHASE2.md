# Arranque fase 2: CRT y los 98 inicializadores, traducidos y más allá de la protección — 2026-11-17

**Qué se ejecuta.** Lo que el punto de entrada real de la CRT Metrowerks (`0x64a380`, al que solo salta el *wrapper*) ejecuta antes de WinMain:
1. `0x653460(0x7eba68)`;
2. la inicialización de la CRT `0x655490`: TLS, cerrojos, datos por hilo, manejadores estándar, línea de órdenes y entorno;
3. los 98 inicializadores estáticos de `.CRT`, en orden.

La fase 1 solo cubría 86 inicializadores sueltos.

**Protección.** No se ejecuta nada del *wrapper*. Las llamadas al stub de cabecera `0x400080` las resuelve `runtime/protection_redirect.c` con la tabla del propio archivo. El sustituto reproduce también las escrituras del stub en la pila (`pushad` y la dirección resuelta), de modo que la pila coincide byte a byte con x86. Las llamadas a la ranura `.prus` `[0x850000]` se despachan por sitio según `tools/resolve_protection_redirects.py`. En este arranque hay 4 `GetLastError` y ningún disparador.

**Traducción.** `tools/lift_boot_phase2.py` traduce exactamente las funciones que se ejecutan, según la traza x86 del mismo arranque: **338 funciones y 12 494 instrucciones**. Un destino que nunca se ejecuta (19) queda como parada que falla de forma controlada. El código ejecutado fuera de cualquier función traducida (destinos de vtables) se añade como raíz hasta cubrirlo todo. Cambios auditados en `tools/recomp_lift.py`:
- **x87** (`x87=True`), en 6 funciones:
  - accesos `float`/`double` comprobados (`MEMF`/`MEMD`);
  - aritmética, incluidas las formas inversas, por `mh_x87_*`;
  - `fsqrt` por `mh_x87_sqrt`;
  - `fistp` de 64 bits por `mh_x87_st0_to_i64`, que da el «entero indefinido» de x87 en lugar del comportamiento indefinido de C;
  - lista cerrada de helpers de pila x87 de PCRecomp, y cualquier otra llamada matemática aborta.
- **Helpers puros de flags** de `adc`/`sbb`/`clc`.
- **`jmp [importación]`** con bytes `FF 25` comprobados, como salto final despachado (`MH_RECOMP_IJMP_AT`).
- **`dispatch_slots`**: llamadas por la ranura `.prus` despachadas por su valor.
- **`provided`**: el stub de cabecera lo aporta el runtime.

**Shims nuevos.**
- `runtime/win32_thread.c`: último error y TLS.
- `runtime/win32_process.c`:
  - línea de órdenes `"manhunt.exe"` y entorno vacío;
  - `GetStdHandle` devuelve `NULL` (proceso GUI sin consola);
  - pseudo-handle de proceso;
  - `DuplicateHandle` sobre `NULL` falla con `ERROR_INVALID_HANDLE`;
  - `CreateEventA` devuelve manejadores distintos, sin modelar todavía la señalización.

**FPU.** Unicorn arranca con la palabra de control a 0 (precisión simple, excepciones desenmascaradas). Un proceso de Windows arranca con `0x027F`, y ese es el valor que usan la referencia y el arnés. Con 53 bits de precisión, la aritmética x87 redondea igual que el `double` del modelo traducido.

**Prueba.** `tests/boot_phase2_native.c` (`worksafe.test_boot_phase2()`) frente a la referencia de `tools/trace_static_init_x86.py` (Unicorn). Se compara:
- los registros tras cada uno de los 100 pasos;
- los recuentos de las 20 API;
- las redirecciones, el último error, el TLS y los eventos;
- el CRC-32 de `.data`, `.bss`, la imagen completa salvo las dos tablas de importaciones, 16 KiB de pila y el heap global;
- la palabra de control de la FPU.

**Coincide en Windows x64 y en el S25 `SM-S938B` (ARM64).** Binario ARM64 validado: `2480c8e4…`.

**Límites.** Un solo hilo. Los eventos no se señalizan. `GetTickCount`, `ExitProcess`, `MessageBoxA`, `GlobalFree` y `DeleteCriticalSection` no se llaman en este arranque y fallan de forma controlada si se alcanzan. La aritmética x87 se hace en `double`, sin precisión extendida de 80 bits. Los 16 disparadores de la protección siguen sin resolver. El siguiente paso es WinMain (`0x4c1080`).
