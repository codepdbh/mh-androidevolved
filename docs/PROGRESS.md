# Progreso

2026-11-13: añadidos `recomp/x87_semantics.h` y `tests/test_x87_semantics.c` (perfil `test_x87_semantics()`, CTest y modo `--x87-semantics` del arnés de tiempo, que también corre en la sesión del S25). Caso NaN incorporado a la candidata de tiempo; Windows x64 coincide. Ejecución en el S25 bloqueada: el dispositivo dejó de aparecer en `adb devices`.

2026-11-13: traducidas `0x5daa50` (x87) y `0x5ea2b0` como undécima y duodécima dependencias de la candidata de tiempo (`tools/lift_time_x87_dependency.py`). Corregida la semántica de `fdivp` ante divisor cero y eliminados los punteros crudos flotantes. Coincidieron 256 + 12 casos y cuatro fallos en Windows x64 y en el S25.

2026-11-13: traducida la sonda de pila `0x648540` como décima dependencia real de la candidata de tiempo (`tools/lift_time_stack_probe.py`), con verificación de bytes en la sonda x86. Coincidieron 256 + 12 casos y cuatro fallos en Windows x64 y en el S25.

2026-11-13: traducidas `0x481340` y `0x611640` como octava y novena dependencias de la candidata de tiempo. Añadido `mh_recomp_rep_movs` al adaptador de memoria comprobada, con prueba propia (`test_checked_rep_movs()`, también en CTest): 20 160 casos y cuatro rechazos. La herramienta de traducción rechaza cualquier helper del runtime sin comprobar. Coincidieron 256 + 12 casos y cuatro fallos en Windows x64 y en el S25; 19 pruebas del supervisor pasaron.

2026-11-13: traducido el selector de modo `0x5daa20` como séptima dependencia real de la candidata de tiempo, con verificación de las nueve instrucciones y de los bytes en la sonda x86. Coincidieron 256 + 12 casos y cuatro fallos en Windows x64 y en el S25 (ARM64), cubriendo ambas ramas del selector; 19 pruebas del supervisor pasaron.

2026-11-13: publicado el repositorio en GitHub sin datos del juego, código generado ni el icono derivado de la referencia (sustituido por un marcador neutro). Añadidos perfiles del supervisor para compilar el arnés de tiempo en ARM64 y ejecutarlo en una sola sesión ADB; 19 pruebas del supervisor pasaron y la comparación en Windows x64 se repitió sin cambios. En el S25 coincidieron 256 + 12 casos frente a Unicorn y los cuatro fallos esperados; limpieza confirmada. Ver `docs/evidence/S25_TIME_CANDIDATE.md`.

2026-11-13: un intento de la prueba de despacho se interrumpió por reinicio de ADB durante `mkdir`; una inspección posterior de solo lectura no encontró directorios temporales del proyecto. Preparado un perfil de una sesión con transferencia acotada, validación sintáctica, hash y limpieza confirmada; 16 pruebas del supervisor pasaron. El intento real sigue aplazado por memoria libre insuficiente.

2026-11-13: endurecido el perfil ADB ante caídas de RAM durante la prueba: el mínimo inicial es 1536 MiB, se detienen operaciones por debajo de 1024 MiB y se mantiene la limpieza. Pasaron diez pruebas del supervisor, incluida la limpieza simulada tras una caída de memoria. La prueba ARM64 de despacho sigue pendiente en el S25.

2026-11-13: compilada una prueba ARM64 de despacho y probado su perfil de dispositivo con ADB simulado. El intento real se rechazó antes de acceder al teléfono con aproximadamente 518 MiB libres. Las dos pruebas anteriores del S25 no cambiaron.

2026-11-13: las dos pruebas sintéticas ARM64 de memoria y PE32 pasaron en un Galaxy S25 Ultra `SM-S938B` con hashes verificados. El supervisor limpió los archivos temporales. No se instaló una APK ni se ejecutó el juego.

2026-11-13: preparado un perfil supervisado para ejecutar dos pruebas ARM64 sintéticas en un Galaxy S25 autorizado, con verificación de hashes y limpieza de archivos temporales. Tres pruebas con ADB simulado verifican selección inequívoca, rechazo de modelo incorrecto y limpieza ante error de hash; no se ha detectado ni modificado ningún teléfono.

2026-11-13: traducidos un candidato DirectInput de 28 instrucciones y su trampolín; ambos se enlazaron como objeto ARM64 con 17 símbolos externos pendientes. Preparadas y verificadas dos pruebas ARM64 sintéticas para un teléfono; ADB aún no detectó dispositivos y ninguna se ejecutó en hardware.

2026-11-13: implementados enumerador PE32 y plan transaccional de importaciones. El ejecutable local produce 165 importaciones coincidentes con un lector independiente; sin resolutores, las 165 se marcan pendientes y la imagen no cambia. Pruebas sintéticas cubren nombres, ordinales, corrupción, resultados ausentes, entradas solapadas y cambios posteriores al plan. La biblioteca Android compiló por CMake; no se implementaron las API importadas.

2026-11-13: las dos funciones JNI pasaron pruebas en Windows x64 con una tabla JNI simulada: diagnóstico, rechazo por tamaño, PE local válido y copia corrupta. El archivo original se abrió en modo lectura y se verificó su hash antes y después. El primer compilador de host no pudo iniciar su enlazador; el arnés compiló con MSVC usando una copia local del encabezado JNI adaptada solo en visibilidad. Falta la prueba en Android.

2026-11-13: implementado el mapeo PE32 acotado, probado con datos sintéticos y con las 15 secciones del ejecutable local como datos de solo lectura. El mapa coincidió con una copia independiente y se comprobó el hash del archivo antes y después. Añadida conexión JNI al selector Android; Java, biblioteca JNI y CMake compilaron, sin ejecución Android. El test JNI simulado de host quedó aplazado por memoria libre insuficiente.

2026-11-13: la ruta gráfica pasó 12 casos con dos modos sintéticos y se repitieron los nueve de un modo y el caso nulo. Las comparaciones se limitaron a registros, flags aritméticos y pila observada; no se creó un dispositivo Direct3D ni se probó ARM64 en un teléfono.

2026-11-13: en un caso sintético de creación Direct3D nula, Unicorn registró una lectura de cuatro bytes en dirección cero y el adaptador detuvo el acceso fuera de la región de prueba. No se ha implementado todavía manejo general de excepciones Win32.

2026-11-13: ampliada la comparación del candidato gráfico con nueve casos sintéticos de enumeración de un modo, más los tres casos sin modos. La variante con retornos precisos coincidió en registros, flags y pila observada frente a Unicorn. Un primer intento detectó que el doble de liberación no contemplaba el retorno temprano; se corrigió el doble y se repitió. Sin Direct3D ni ejecución ARM64.

2026-11-13: comparada una ruta del candidato gráfico con tres casos y dobles Direct3D, sin ventanas. Los registros y flags coincidían, pero dos posiciones de pila diferían por el centinela de retorno de PCRecomp. Se adaptaron cinco sitios para preservar sus direcciones x86 y los tres casos coincidieron también en la pila observada; el objeto ARM64 compiló. Retornos indirectos y Direct3D real pendientes.

2026-11-13: añadido adaptador de despacho que falla ante llamadas y saltos indirectos no resueltos. Pasó pruebas sintéticas de éxito, fallos, centinela y traza en Windows x64. La función gráfica y su trampolín compilaron juntos para ARM64 con los adaptadores de memoria y despacho; 20 símbolos siguen externos. No se ejecutó esa unidad ni se implementó Direct3D.

2026-11-13: conectado el módulo de memoria a un diagnóstico JNI del launcher. Compilados Java y biblioteca ARM64; la biblioteca pasó construcción por Clang y por CMake y verificación estática del símbolo JNI. CMake necesitó permitir hasta ocho procesos bajo el Job Object con un trabajador y límite de 512 MiB. Sin prueba en dispositivo ni APK.

2026-11-13: mapeadas 343 referencias candidatas a importaciones y 93 llamadas candidatas a trampolines mediante barrido estático. Traducidos un candidato de 84 instrucciones que llama al trampolín de Direct3DCreate8 y el propio trampolín; ambos compilaron y se combinaron en un objeto ARM64 reubicable, con 18 símbolos externos pendientes. Sin ejecución ni gráficos.

2026-11-13: ampliado el adaptador con accesos de 64 bits y flotantes, con pruebas de valores desalineados y límites en Windows. El candidato x87 `0x409960` se tradujo y compiló a ARM64; tres cargas se adaptaron individualmente a memoria comprobada. Esa variante coincidió con Unicorn en 653 casos finitos y 288 especiales en Windows x64, sin comparar excepciones ni estado x87 completo.

2026-11-13: el adaptador admite ahora accesos desalineados de 16 y 32 bits mediante miembros empaquetados en hosts little-endian. El candidato pasó 653 casos diferenciales con cuatro alineaciones en Windows x64 y el acceso fuera de rango siguió fallando. El objeto con adaptador compiló para ARM64, sin ejecución. Las pruebas de memoria y del supervisor pasaron.

2026-11-13: creado un adaptador experimental de memoria acotada para el candidato `0x40a020`. Pasó 167 casos en Windows x64 con el encabezado PCRecomp real; dos pruebas verificaron rechazo de acceso fuera de rango y desalineado. La traducción con adaptador compiló a objeto ARM64 sin enlazar. El adaptador no cubre todos los accesos ni permite aún desalineaciones x86.

2026-11-13: 167 casos del segundo candidato también coinciden entre Unicorn y el C generado compilado para Windows x64 con `recomp_types.h` real, bajo el supervisor. La primera compilación no pudo iniciar el enlazador con un máximo de dos procesos; pasó con máximo cuatro y 512 MiB. No se probó ARM64 ni se integró el juego.

2026-11-13: ampliada la comparación del candidato `0x40a020` a 167 entradas sintéticas. Se compararon salida, registros, pila, objeto, tabla y seis flags aritméticos; todos coinciden en el entorno de prueba. Se vinculó la referencia al hash del ejecutable y de la traducción. Esto no prueba el runtime real ni todos los estados posibles. Gradle sigue aplazado por presión de memoria.

2026-11-13: se tradujo un segundo candidato x86 y se compiló para ARM64. Cinco casos sintéticos compararon el x86 aislado en Unicorn con el C generado en WebAssembly: coinciden salida, registros generales y pila observada. Se usaron macros de prueba; faltan flags, el resto de memoria, el runtime real y ejecución en ARM64. Gradle continúa aplazado por memoria libre insuficiente.

2026-11-13: inspecci?n inicial; localizados ejecutable y DLL del juego, sin ejecutarlos. Construido inventariador est?tico y supervisor experimental restrictivo. El inventario no identifica comportamiento de carga din?mica, motor, protecci?n ni acciones reales; se requiere an?lisis adicional. Siguiente paso: revisar resultados, robustecer y probar el supervisor, estudiar licencias y c?digo de los proyectos de referencia e investigar PCRecomp sin eludir protecci?n.

2026-11-13: a?adido proyecto Android inicial y 162 PNG/SVG reproducibles. La verificaci?n de assets pas?; el launcher sigue sin compilarse ni ejecutarse. Ninguna acci?n de juego se ha conectado ni validado. El supervisor no admite todav?a el ?rbol de procesos de Gradle.

2026-11-13: supervisor ampliado con l?mites por trabajo, prueba de cierre de descendientes, umbral de memoria y perfiles de Gradle offline y javac. Cinco pruebas aprobadas. Compilaci?n real aplazada por presi?n de RAM. A?adida comparaci?n SHA-256 del ejecutable en Android sin ejecuci?n; no compilada ni validada en dispositivo.

2026-11-13: compilado aisladamente el launcher Java y un m?dulo inicial de memoria invitada para Android AArch64. Se verific? la cabecera ELF del objeto; las pruebas C todav?a no se han ejecutado. Gradle sigue aplazado por memoria. Revisados los archivos locales de controles: la configuraci?n enumera modos, pero los archivos _key son teclados de texto y no mapeos de gameplay.

2026-11-13: pruebas funcionales de memoria invitada aprobadas en WebAssembly, con memmove de prueba: l?mites, extremo de 32 bits, endianidad, errores sin cambios y solapamiento. El ejecutable ARM64 y Gradle a?n no se han probado. Revisadas instrucciones y licencia MIT de PCRecomp; integraci?n pendiente.
