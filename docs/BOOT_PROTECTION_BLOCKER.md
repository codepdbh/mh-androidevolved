# Protección del ejecutable en el arranque — 2026-11-17

## Qué se observó (análisis estático y referencia x86 aislada)

- El punto de entrada inventariado (`0x851370`) está en `.prus`, no en `.text`. `.prus` y `.izbf` están casi vacías en el archivo (entropía 0,12 y 0,01): su contenido se genera en tiempo de ejecución. Es el patrón de un *wrapper* de protección.
- El código del juego usa dos redirecciones en lugar de la tabla de importaciones normal:
  1. **Stub de cabecera `0x400080`** (91 sitios `call 0x400080`): código del propio archivo que busca la dirección de retorno en una tabla de pares (ranura IAT, retorno) que termina en `0x40087c` y salta a la importación correspondiente.
  2. **Ranura `[0x850000]` en `.prus`** (37 sitios `call dword ptr [0x850000]`): se rellena en tiempo de ejecución.
- El décimo primer inicializador estático (`0x455ff0`) llega a la ranura a través de los datos por hilo de la CRT Metrowerks (`0x612eb0`).

## Política

`AGENTS.md` (actualizado por el usuario el 17-11): se pueden eludir protecciones porque es la copia legítima del propio usuario. El port **no ejecuta** el código del wrapper ni modifica el ejecutable; sustituye las dos redirecciones en el runtime (HLE). Los resultados se quedan en `private/` y no se distribuyen.

## Solución (implementada)

- `tools/resolve_protection_redirects.py` verifica los bytes del stub y genera `private/analysis/protection/redirects.json` y `redirect_sites.h`:
  - **Stub de cabecera:** las 91 entradas de la tabla coinciden exactamente con los 91 sitios de llamada, sin sobrantes ni faltantes, y todas apuntan a ranuras de importación normales (`GetCommandLineA`, `TlsFree`, `ReadFile`, Miles, Bink, registro, ventanas…). La resolución es exacta.
  - **Ranura `.prus`:** cada sitio se clasifica con patrones estrictos:
    - 14 `GetLastError` (el resultado se compara con `ERROR_IO_PENDING`/`ERROR_FILE_NOT_FOUND`/`ERROR_HANDLE_EOF`/`ERROR_ALREADY_EXISTS` tras una API fallida, o se pasa a `_dosmaperr`, o es el caso de `TlsGetValue` en la CRT).
    - 7 validaciones de puntero `IsBad*Ptr` en el manejo de excepciones de la CRT.
    - **16 disparadores antimanipulación**: cargan valores mágicos en registros (`0xdead/0xbeef/0xfeed`, `0xabba/0xbaba`…) y, si el resultado no es el esperado, activan banderas de penalización (`[0x756244]=2`, `[0x755e50]=1`, `[0x7d6148]=0x2d`…). **Pendientes**: fallan de forma controlada hasta analizar cada uno. Ninguno está en el arranque.
- `runtime/protection_redirect.{h,c}`: recorrido de la tabla de cabecera sobre la imagen mapeada, búsqueda por dirección de retorno y validación de punteros sobre la memoria del invitado.
- `runtime/win32_thread.{h,c}`: último error y TLS con la semántica documentada (`TlsGetValue` pone `ERROR_SUCCESS` al acertar, que es lo que consulta la CRT).
- `tests/test_protection_redirect.c`: 86 comprobaciones sintéticas (`worksafe.test_protection_redirect()`), que pasan en Windows x64.

## Resultado en la referencia x86

`tools/trace_static_init_x86.py` ya no se detiene en el wrapper. Ejecuta, en el orden del punto de entrada real de la CRT (`0x64a380`, al que solo salta el wrapper), `0x653460(0x7eba68)`, la inicialización de la CRT `0x655490` (TLS, cerrojos, manejadores estándar, línea de órdenes, entorno) y los **98 inicializadores estáticos: 100 de 100 completados**, con 4 `GetLastError` redirigidos y sin entrar nunca en `.prus`/`.izbf`.

APIs nuevas modeladas en la referencia: `TlsAlloc`/`TlsFree`, `GetStdHandle` (proceso GUI sin consola: `NULL`), `GetCurrentProcess` (pseudo-handle `-1`), `DuplicateHandle` sobre `NULL` (`ERROR_INVALID_HANDLE`), `GetCommandLineA` (`"manhunt.exe"`), `GetEnvironmentStrings` (bloque vacío) y `FreeEnvironmentStringsA`.

## Lo que falta

- **Traducción (17-11, hecho):** la fase 2 se ejecuta traducida sobre estas redirecciones; ver `evidence/BOOT_PHASE2.md`.
- **Disparadores:** analizar los 16 sitios y fijar el resultado que el juego espera de cada uno.
- **WinMain:** después de los inicializadores, el punto de entrada llama a `0x4c1080(hInstance, 0, cmdline, nShowCmd)`.
