# Diagnóstico Android en S25 — 2026-11-13

Con el SDK Android local, `scripts/worksafe.py` compiló recursos con AAPT2, compiló Java, generó DEX con D8, incorporó la biblioteca ARM64 previamente compilada, alineó y firmó una APK con la clave local de depuración. La firma se comprobó con `apksigner verify`. Los procesos se ejecutaron secuencialmente bajo el supervisor; no se usó Gradle ni se incorporaron archivos comerciales del juego.

En el Galaxy S25 Ultra `SM-S938B` se comprobó previamente que el paquete `com.manhuntae.android` no existía. ADB informó de instalación exitosa; `am start -W` comunicó `Status: ok`, arranque frío y actividad esperada, y `pidof` confirmó el proceso. Esto no verifica el contenido visual, el ciclo de vida completo, la selección mediante SAF ni el resultado de JNI; no se ejecutó el juego. La APK mantiene Jugar desactivado.

La prueba independiente `dispatch_test` ARM64 pasó mediante una sesión ADB supervisada con validación del modelo y ABI, verificación de hash y limpieza confirmada. Se trata de datos sintéticos y no acredita funcionamiento del juego.

Después, el usuario seleccionó la carpeta del juego en el teléfono. La lectura de accesibilidad del diagnóstico, limitada a su actividad en primer plano, mostró «Memoria nativa: comprobación básica correcta» y «Ejecutable identificado; estructura PE e importaciones comprobadas». Esto confirma el flujo SAF y las dos llamadas JNI para esta ejecución; los demás datos no se verificaron individualmente. La inspección no confirma el juego, la representación del icono en el lanzador ni los ciclos de vida posteriores.
