# Cargador de ranuras `0x605750` en ARM64 — 2026-11-16

**Qué hace la función** (deducido del código, sin documentación): compone una ruta concatenando una cadena del objeto (`this+0x2ac`), el prefijo global `[0x7d7d88]` y el nombre `0x7d7c10 + 32·índice`. Abre el archivo con `CreateFileA` en lectura y disposición «abrir existente», y lee siete bloques `(búfer, tamaño)` con `0x6059a0`, exigiendo cada vez el tamaño exacto. Después hace una lectura de 1 byte para comprobar que no sobran datos y cierra. Si sobran bytes, marca la ranura como inválida (`[this + índice·84 + 0xc] = 0xffffffff`). Devuelve 1 si todo es correcto y 0 en caso contrario.

**Actualización:** el cargador usa ya el asignador real del juego (ver `S25_ALLOCATOR.md`); sigue coincidiendo con x86 en 16 casos en el S25.

**Traducción.** `tools/lift_loader_strings.py` tradujo las siete funciones que faltaban: `0x6059a0`, la clase de cadenas (`0x4f2400`, `0x4f2590`, `0x4f2a40`, `0x4f28c0`, `0x4f2520`) y la envoltura de asignación `0x401020`. Se validaron con capstone 19 llamadas directas y se fijaron sus retornos exactos, sin punteros crudos ni helpers sin comprobar. Junto con las unidades existentes (`0x605750`, las funciones de archivo, `0x401030` y `0x611640`), el arnés ejecuta 21 funciones traducidas del juego. Quedan como dobles el asignador de pool `0x401350` y la liberación `0x401b00`.

**Prueba.** `tests/loader_native.c` (solo Android) crea archivos de ranura sintéticos bajo su directorio temporal y abre la ruta del juego, `data\save\slotN.bin`, a través de `runtime/readonly_handles`. `tools/probe_loader_x86.py` ejecuta el `.text` real del ejecutable verificado en Unicorn con las mismas entradas, dobles equivalentes y emulación del mismo subconjunto de API, con la misma numeración de handles. Se cubren 4 escenarios × 4 alineaciones: ranura exacta (devuelve 1), byte sobrante (0 y ranura marcada), archivo corto (0) y archivo inexistente (0). Se comparan los registros, seis banderas, la pila, el objeto con los marcadores, los búferes, el heap con el estado del asignador y los recuentos de llamadas a la API.

**Resultado en el S25 `SM-S938B`:** los 16 casos coinciden con x86. Binario `b85150a15162167a0a233475f19ee8eb4e2584f05791098c55a0ee816509f063`; limpieza confirmada. El manifiesto de fuentes está en `private/analysis/loader/android/manifest.json`.

**En la app.** El botón «Ejecutar prueba de código traducido» ejecuta también este cargador en un directorio de la caché de la app y compara el SHA-256 de su salida con la validada. En el teléfono resultó **idéntico a x86** (todo el botón tardó 941 ms).

**Límites.** Los archivos de ranura son sintéticos; no se ha identificado qué archivos reales del juego carga esta función ni se ha probado su alcanzabilidad. El asignador real del juego no está traducido. La API es solo el subconjunto de lectura observado, sin modos de compartición, `GetLastError` ni conversión de mayúsculas. El juego sigue sin arrancar.
