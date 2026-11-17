# Estado vigente — 17 de noviembre de 2026

El juego todavía no es jugable. La APK instalada es un diagnóstico: selecciona los archivos y examina el ejecutable mediante JNI. Las pruebas de rutinas traducidas se ejecutan en un arnés aislado; no son el arranque del juego.

## Verificado

- **Protección sustituida en la referencia x86 (17-11):** las 91 llamadas por el stub de cabecera se resuelven exactamente desde su tabla; de las 37 de la ranura `.prus`, 14 son `GetLastError` y 7 validaciones de puntero (sustituidas), y 16 son disparadores antimanipulación pendientes. Con el arranque real de la CRT (`0x64a380` → `0x655490`), los 98 inicializadores estáticos completan en x86 (antes 10). El código traducido sigue en la fase 1; ver `BOOT_PROTECTION_BLOCKER.md`.
- **Arranque fase 2 traducido (17-11):** la inicialización de la CRT y los 98 inicializadores estáticos (338 funciones, 12 494 instrucciones, x87 incluido) se ejecutan traducidos, pasando por las redirecciones de la protección sin ejecutar el *wrapper*. Coinciden con x86 en registros, API, TLS, `.data`, `.bss`, imagen, pila, heap y FPU en Windows x64 y en el S25. Ver `evidence/BOOT_PHASE2.md`.
- **Direct3D 8 (17-11):** shim `IDirect3D8` en memoria del invitado. El selector de refresco `0x4c0830`, traducido, coincide con x86 en 48 casos en Windows x64 y en el S25. La fase 1 del arranque se repitió en el S25 sin regresiones. Ver `evidence/S25_GRAPHICS_D3D8.md`.
- **Arranque fase 1 (17-11):** imagen real del juego mapeada y 86/98 inicializadores estáticos ejecutados traducidos en el S25, idénticos a x86. Ver `evidence/S25_BOOT_PHASE1.md`.
- **Heap del juego y shims Win32 de memoria (16-11):** 19 funciones; `GlobalAlloc` y secciones críticas implementadas en `runtime/win32_memory.c`. Cargador sobre la pila completa: 52 funciones, idéntico a x86 en el S25 y en la app. Ver `evidence/S25_HEAP_AND_WIN32_MEMORY.md`.
- **Asignador del juego (16-11):** 12 funciones traducidas; 960 operaciones idénticas a x86 en Windows y S25. Integrado en el cargador (33 funciones) y en la app. Ver `evidence/S25_ALLOCATOR.md`.
- **Cargador `0x605750` (16-11):** 21 funciones traducidas con apertura y lectura reales de solo lectura; 16 casos idénticos a x86 en el S25 y dentro de la app. Ver `evidence/S25_LOADER.md`.
- **App en el S25 (16-11):** autodiagnóstico ARM64, lectura real de `manhunt.exe` por descriptor SAF con la capa del port y ejecución dentro de la app del código traducido de la candidata de tiempo, con salida idéntica a la validada frente a x86. APK privada por contener ese código; ver `evidence/S25_APP_SELFTEST.md`.
- S25 Ultra SM-S938B conectado y autorizado; carpeta `/sdcard/mh-androidevolved` presente.
- Recorrido anterior de selección de carpeta, identificación del ejecutable y diagnóstico JNI en el teléfono.
- Traducciones de la candidata de tiempo y trece dependencias, con pruebas aisladas de 256 + 12 casos en Windows y S25, incluido el NaN; las demás funciones son sustitutos de prueba.
- Corrección de NaN x87 comprobada también en ARM64 en esta sesión: coincidieron 256 + 12 casos, pasaron 12 comprobaciones de los helpers y cuatro fallos esperados; limpieza confirmada.
- Nuevo control de integridad de fuentes del arnés: cinco pruebas pasan; un manifiesto anterior o una cabecera cambiada impide la subida a ADB. El arnés actual registra 22 archivos locales. Las 19 pruebas del supervisor también pasan.
- Tres dependencias de `0x605750` se tradujeron y pasaron 64 casos aislados y dos fallos esperados en Windows y S25. La lectura de archivos está simulada; ver `evidence/S25_LOADER_HELPERS.md`.
- Posteriormente se implementó un proveedor real de solo lectura y el mismo envoltorio leyó un archivo temporal y las cabeceras de la copia del juego en el S25. Pasaron EOF, lecturas parciales y rechazos; hashes sin cambios y limpieza confirmada. Sigue siendo un arnés aislado con un handle de prueba; ver `evidence/S25_REAL_READONLY_STREAM.md`.

## Bloqueo de esta sesión

La RAM libre del PC fluctúa; los primeros intentos se detuvieron por debajo del umbral de 1536 MiB. Cuando volvió a haber memoria suficiente se reconstruyó el arnés y se ejecutó correctamente en el teléfono.

## Próximo paso comprobable

Último trabajo: la tabla de archivos y apertura relativa de solo lectura pasó sus pruebas en el S25 al reconectarlo. Se añadieron tres envoltorios traducidos y pasó abrir/leer/cerrar archivos temporales y las cabeceras de la copia del juego, usando adaptadores de API específicos del arnés. La prueba de FIFO quedó excluida por la política del dispositivo. Ver `evidence/S25_READONLY_HANDLES.md`. La aplicación sigue necesitando integración mediante SAF y semántica general de las API antes de usar este recorrido fuera del arnés.

El envoltorio `0x401030` ya se integró y pasó las comparaciones en el S25; su función interna `0x401b00` sigue simulada. La candidata `0x605750`, de 180 instrucciones, está traducida y compilada como objeto ARM64 separado, pero no se ha ejecutado. Tres de sus nueve dependencias directas ya tienen pruebas aisladas. Existe un proveedor real de lectura por descriptor, probado con el envoltorio en el S25; faltan apertura por nombre/SAF, tabla de handles e integración. El arnés principal todavía usa un sustituto para `0x605750`. El siguiente trabajo es completar las otras dependencias y preparar su prueba aislada antes de integrarla.

## Trabajo que aún separa el arnés del juego

La función `0x605750`, el temporizador y métodos virtuales siguen sustituidos en las pruebas. Faltan también rutinas adicionales, APIs de Windows y COM, integración del arranque y del despacho con el ejecutable completo, renderizado, audio y controles. Un caso de prueba que pase no cubre estas funciones ni demuestra equivalencia general. El estado histórico detallado está en `STATUS.md` y la evidencia de Android en `evidence/S25_TIME_CANDIDATE.md`.
