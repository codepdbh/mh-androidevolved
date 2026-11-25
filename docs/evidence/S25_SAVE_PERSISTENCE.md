# Persistencia de partidas y validación de fuentes — 2026-11-24

## Implementación

- `runtime/port_api.c`: la partida se escribe en un archivo temporal hermano. Se comprueban escritura, vaciado, sincronización y cierre antes de reemplazar el destino. Windows usa `MoveFileExA`; Android usa `rename`.
- Si falla el guardado, `CloseHandle` devuelve fallo y establece `GetLastError`. La partida anterior se conserva si el fallo ocurre antes del reemplazo.
- Crear o truncar un archivo vacío también se persiste, aunque no haya una llamada posterior a `WriteFile`.
- Los datos originales siguen siendo de solo lectura. Las escrituras de la app van a su directorio privado de partidas; las pruebas usan carpetas temporales propias.
- `scripts/worksafe.py`: la validación de WinMain registra hashes del grafo local de fuentes C, las referencias de cada escenario y las partidas semilla. La biblioteca del juego registra su propio grafo de fuentes y el hash del manifiesto validado. Una fuente cambiada o un manifiesto antiguo impide empaquetar una biblioteca como vigente.
- El primer intervalo del medidor de rendimiento JNI parte de un reloj inicializado.
- `runtime/touch_input.h` y JNI: la interfaz entrega teclas y movimiento a un buzón protegido por mutex. Solo el hilo del juego modifica el estado del port; una pulsación y su liberación entre dos fotogramas conservan al menos un fotograma de pulsación.

## Compilación y pruebas realizadas

`test_port_saves()` compiló con MSVC para Windows x64 y con el NDK para Android ARM64. Ejecutó el mismo test sintético de API en ambos sistemas:

```text
port saves: 54 checks passed; persistent reopen, replacement, readonly seeds, empty saves, open/rename failures; cleanup OK
```

El S25 confirmó `MHAE_TESTS_PASSED` y `MHAE_CLEANUP_OK`. Se prueban la reapertura mediante una instancia nueva del port, el reemplazo de datos, las semillas de solo lectura, el truncado, la creación sin escritura y los fallos de apertura del temporal o reemplazo final. No se usa código ni contenido del juego en este test.

La suite Python pasó finalmente 48 pruebas. Incluye rechazo de fuentes o bibliotecas obsoletas (incluso conservando la fecha), comprobación del teléfono antes de subir archivos, integridad de los puntos de reanudación y finalización de APK preparadas.

La entrada pasó 274 comprobaciones sintéticas tanto en Windows como en ARM64 en el S25: toques cortos, teclas mantenidas, varias teclas simultáneas, acumulación y consumo del ratón, y saturación sin desbordamiento. La unidad JNI actual pasó además la comprobación de sintaxis del NDK.

Evidencia local (ignorada por Git):

- `logs/port-saves-host-build.stdout.log` y `logs/port-saves-host-run.stdout.log`.
- `logs/port-saves-arm64-build.stderr.log` y `logs/device-port-saves-session.stdout.log`.
- `logs/python-regression-tests.stderr.log`.
- `logs/touch-input-build.stdout.log`, `logs/touch-input-run.stdout.log`, `logs/touch-input-arm64-build.stderr.log` y `logs/device-touch-input-session.stdout.log`.
- `logs/game-jni-syntax.stderr.log`.

## Límites

Estas pruebas comprueban el almacenamiento sintético; no certifican cargar una partida real desde el menú después de reiniciar Android. No simulan disco lleno, pérdida de energía ni fallos del directorio tras `rename`. El grafo de integridad cubre archivos locales, no las cabeceras del SDK ni la identidad del compilador. La comparación de escenarios del juego y la instalación de la APK se registran por separado.

## Bloqueos observados durante la sesión

Mientras el compilador ARM64 estaba activo, `launch_game_on_s25()` rechazó abrir la app instalada porque la RAM libre cayó por debajo del mínimo de 1024 MiB de `launch_diagnostic_on_s25`. No se envió el lanzamiento a ADB. La compilación supervisada siguió activa; no se alteraron los umbrales ni se usó la anulación de RAM.

## Comparación integral y desconexión del S25

Pasaron los 17 escenarios de WinMain en Windows. El ejecutable actual compiló para ARM64; pasaron 16 escenarios en el S25, incluido `play5` (2000 fotogramas con acciones). En el último, `save`, la sesión solo dejó `MHAE_BEGIN`, sin resultado ni confirmación de limpieza. ADB pasó a detectar un Redmi Note 8 en vez del S25. No se cuenta ese escenario como aprobado.

El intento pendiente está registrado en `private/analysis/winmain/android/pending-validation.json`: directorio `/data/local/tmp/mhae_d435ae3ce2de62db`, dispositivo original `R5GL70TXWMP`, limpieza sin confirmar. No se intentó limpiarlo en otro dispositivo.

Se recuperó explícitamente un punto de reanudación a partir del binario y los resultados conservados de esta sesión: se volvieron a comparar los 17 resultados de Windows y los 16 completos de Android. Se comprobó que los archivos fuente precedían a la compilación y que las salidas conservadas correspondían a las nuevas ejecuciones, no al caso `save` antiguo. Esta recuperación está identificada como tal en el registro; no se presenta como un punto guardado antes de la compilación. `private/scripts/recover_validation_checkpoint.py` conserva el procedimiento local.

Las siguientes tandas crean puntos de reanudación tras compilar y después de cada comparación completa. `resume_winmain_on_s25()` exige los mismos hashes de fuentes, referencias, binarios y resultados. La limpieza pendiente se comprueba en el dispositivo original, sin borrado recursivo y verificando el hash del ejecutable si aún existe.

## Biblioteca y APK preparadas

- `libmh_game.so` compiló; SHA-256 `c287b2d5be78a23d96bc251481db810d29153e441482d1eae5ecef951ed4d91a`.
- `build/android-diagnostic-apk/prepared-debug.apk` compiló y pasó la verificación de firma. Es una compilación privada depurable, para poder inspeccionar partidas mediante `run-as` cuando esté instalada.
- La preparación no crea el registro de validación terminada. `promote_prepared_game_library()` y `finalize_prepared_apk()` exigen completar la comparación del S25 y conservar idénticas las fuentes y los binarios. No se instaló esta APK.
- Evidencia: `logs/game-library-build.*.log`, `logs/diagnostic-sign-verify.stdout.log`, `private/analysis/game/android/prepared.json` y `build/android-diagnostic-apk/prepared-apk.json`.

## Candidatos adicionales, sin integrar

`stage_save_load_candidates()` realiza desensamblado estático y traducción de siete entradas que son paradas de WinMain: `0x605750`, `0x605bf0`, `0x607b00`, `0x607d60`, `0x607df0`, `0x607fc0` y `0x608030`. El cierre generado contiene ocho funciones y 625 instrucciones. Compiló como objeto ARM64 (`dc6e78b5c5c4d7707e49048d3a936e17860a145be7f9ae41046b617f1160a276`).

No se enlazó, ejecutó ni comparó con x86; tampoco se incorporó a la app. Las dependencias directas hacia paradas previas quedaron cubiertas en este candidato, pero el análisis no demuestra qué destinos indirectos se alcanzarán. Detectó dos imports ausentes en `runtime/port_api.c`: `DeleteFileA` y `SetFileAttributesA`. Requieren implementación y pruebas antes de usar estas ramas. Los artefactos y el manifiesto de compilación permanecen en `private/analysis/save_load_candidates/`.
