# Problemas conocidos

- PCRecomp traduce `fdivp` con una protección que devuelve el dividendo si el divisor es cero; x87 produce ±inf o NaN. Se corrigió solo en `0x5daa50`; cualquier otra traducción con `fdivp` necesita la misma revisión. La FPU se modela con `double` del host, no con precisión extendida de 80 bits ni el control de precisión que Direct3D suele fijar. Hipótesis sin verificar: un `0/0` produce en x87 el NaN indefinido negativo (`0xffc00000`) y en ARM64 el NaN por defecto positivo (`0x7fc00000`); las pruebas actuales no generan NaN.

Actualización posterior: la selección de carpeta y las llamadas JNI de diagnóstico completaron en el S25. No se ha probado la ejecución del juego y los datos ajenos al ejecutable no se han verificado individualmente.

Actualización: se instaló y arrancó una APK privada de diagnóstico en el S25 y la prueba sintética ARM64 de despacho pasó. Los puntos siguientes sobre ausencia de APK y de pruebas de despacho en Android se refieren al estado anterior; siguen pendientes la selección de carpeta, la inspección JNI en pantalla y una implementación capaz de arrancar el juego.

- El juego no arranca: falta recuperación amplia de código, integración del runtime, importaciones y métodos COM; el renderer no existe y no hay APK.
- El punto de entrada utiliza código no convencional, posiblemente empaquetado; no se ha identificado protección ni eludido ningún mecanismo.
- El adaptador de memoria solo cubre las formas indicadas en `docs/ARCHITECTURE.md`; usa una región global y no está probado en Android.
- El despacho comprobado tiene pruebas sintéticas en Windows, pero no está conectado a importaciones reales ni probado en ARM64.
- PCRecomp usa un centinela como dirección de retorno: se observaron dos diferencias de pila frente a x86. Una adaptación de cinco sitios las elimina en tres casos sintéticos, pero no resuelve de forma general los retornos indirectos a direcciones reales.
- Los casos x87 comparan profundidad final, no el estado completo de FPU ni los flags de excepción. Los valores especiales observados no demuestran equivalencia general.
- El launcher, la biblioteca JNI y los assets no se han probado en un dispositivo. La selección de carpeta identifica un ejecutable por hash pero no verifica todos los datos.
- El cargador PE32 solo copia cabeceras y secciones a la base preferida; no resuelve importaciones, relocalizaciones, TLS, protecciones de página ni arranca el ejecutable. La llamada JNI que lo usa aún no se ha ejecutado en Android.
- El plan de importaciones puede enumerar pendientes y aplicar resoluciones completas aportadas por un llamador, pero no proporciona aún implementaciones reales; en la instalación local las 165 importaciones permanecen pendientes.
- Gradle no se ha ejecutado debido al umbral de memoria libre; la compilación nativa CMake pasó de forma aislada.
