# Rutinas auxiliares de la candidata 0x605750 — 16 de noviembre de 2026

Se verificaron estáticamente y tradujeron tres ventanas pequeñas: `0x605e40` (cálculo de dirección), `0x60fea0` (inicialización de un campo) y `0x60ff60` (preparación de argumentos y llamada a la entrada IAT de ReadFile). Se conservaron los datos originales y los resultados de traducción permanecen en `private/`.

Las tres rutinas compilaron como objeto ARM64. Un arnés independiente comprobó 16 casos del cálculo de dirección, 16 de inicialización y 32 de la llamada de lectura, con cuatro alineaciones, tamaños 0/1/7/31 y resultados de éxito/fallo simulados. Se verificaron argumentos, pila, registros, banderas y regiones de memoria según cada caso. Además, una entrada ReadFile ausente devolvió el fallo controlado 74 y un objeto nulo el fallo 70. Estas son comprobaciones contra valores esperados del arnés, no una comparación diferencial exhaustiva con x86.

El arnés pasó en Windows x64 y en el S25. El binario del teléfono se verificó por SHA-256 (`f765a522647c8199431bda8e83e6369df5d2bec599b9216a4b24fb9bf78bf4da`) y se confirmó la limpieza de su directorio temporal. Las fuentes locales se registraron y comprobaron antes y después de compilar y ejecutar.

ReadFile es un sustituto sintético: no abrió ni leyó archivos del juego. No se integraron estas rutinas en la candidata principal, no se modificó la APK y no se demostró que el juego arranque. Para ello faltan las demás rutinas, servicios de archivos y otros componentes del runtime.
