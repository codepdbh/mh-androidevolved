# Estado vigente — 24 de noviembre de 2026

El port ejecuta el arranque, el menú y recorridos del primer nivel como código traducido. Tiene backend OpenGL ES, entrada táctil y guardado separado de los datos originales. La cobertura está limitada a las rutas traducidas: una sesión libre todavía puede alcanzar una función pendiente y detenerse. No se ha validado el juego completo.

## Implementación

- Unidad privada de 4692 funciones traducidas. Arranque CRT, inicializadores y WinMain compartidos entre el arnés de comparación y la app.
- Backend OpenGL ES 3, iluminación, texturas y superficies de render. Cambios recientes: conservar coordenadas de recorte y ofrecer 4:3, imagen estirada o panorámica.
- Controles táctiles de movimiento, cámara y acciones. Buzón con mutex entre la interfaz y el hilo del juego para conservar toques cortos y evitar escrituras concurrentes en el estado del port.
- Guardado en superposición: la app escribe en su almacenamiento privado. Escritura temporal, sincronización y reemplazo comprobados; errores de persistencia comunicados por la API.
- Mezclador y salida AAudio implementados. Falta una comprobación de escucha y sincronización durante una sesión prolongada.
- Compilación de la biblioteca y empaquetado vinculados por hashes a las fuentes y referencias validadas. Los manifiestos antiguos requieren repetir la validación.

## Compilación y pruebas

- 23-11: 17 escenarios comparados con x86 en Windows x64 y Android ARM64 en el S25, incluidos el primer nivel, acciones y guardar. Se instaló la APK de ese estado. Ver `evidence/FIRST_FRAME.md`.
- 24-11: los mismos 17 escenarios vuelven a coincidir en Windows con los cambios actuales. Compiló el ejecutable ARM64 y pasaron 16 escenarios en el S25. Durante el último, `save`, desapareció el S25 de ADB; quedaron pendientes esa ejecución y la confirmación de limpieza de su directorio temporal.
- 24-11: 54 comprobaciones sintéticas de persistencia pasaron tanto en Windows como en el S25, con reapertura, reemplazo, archivos vacíos y fallos; limpieza confirmada.
- 24-11: 274 comprobaciones sintéticas de entrada pasaron en Windows y en el S25; limpieza confirmada.
- 24-11: 48 pruebas Python pasaron. Java compiló y la unidad JNI actual pasó la comprobación de sintaxis del NDK.
- 24-11: compilaron `libmh_game.so` y la APK privada preparada; esta última pasó la verificación de firma. No se instaló. Los manifiestos conservan sus hashes y fuentes, con la validación del S25 todavía pendiente.
- 24-11: se recuperó un punto de reanudación tras comparar de nuevo los 17 resultados de Windows y los 16 completos del S25. Las siguientes tandas guardan automáticamente sus puntos de reanudación; fuentes, binarios o resultados cambiados impiden reutilizarlos.
- 24-11: análisis estático de siete entradas adicionales: ocho funciones y 625 instrucciones generadas en una unidad privada independiente. Compiló como objeto ARM64, sin enlazar ni ejecutar. Detectó dependencias todavía ausentes: `DeleteFileA` y `SetFileAttributesA`. No altera la APK preparada.

Estas pruebas sintéticas no certifican cargar una partida real desde el menú ni una sesión prolongada. Ver `evidence/S25_SAVE_PERSISTENCE.md`.

## Pendiente de esta sesión

ADB detecta ahora un Redmi Note 8, no el S25. Se solicitó reconectar el S25; no se subieron pruebas al Redmi. La comprobación del modelo precede ahora a cualquier subida del ejecutor genérico.

Con el S25 disponible: `resume_winmain_on_s25()` confirma la limpieza del intento interrumpido y repite el escenario pendiente; después `promote_prepared_game_library()` y `finalize_prepared_apk()` comprueban los artefactos ya compilados. `update_diagnostic_on_s25()` conserva los datos de la app, y `launch_game_on_s25()` abre el juego para la prueba visible. Comprobar rendimiento, controles y paradas por código aún no traducido. Guardar, cerrar la app y cargar una partida real requiere evidencia adicional.

## Reglas y límites

El modo de trabajo seguro permanece activo: procesos supervisados por `scripts/worksafe.py`, límites de recursos, ninguna ejecución nativa del juego original ni herramientas gráficas en el PC. Los archivos originales no se modifican. Código traducido, bibliotecas, APK y capturas con contenido del juego permanecen privados. El historial técnico anterior está en `STATUS.md`; los bloqueos antiguos pueden estar resueltos por avances posteriores.
