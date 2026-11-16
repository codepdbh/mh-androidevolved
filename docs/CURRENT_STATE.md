# Estado vigente — 16 de noviembre de 2026

El juego todavía no es jugable. La APK instalada es un diagnóstico: selecciona los archivos y examina el ejecutable mediante JNI. Las pruebas de rutinas traducidas se ejecutan en un arnés aislado; no son el arranque del juego.

## Verificado

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
