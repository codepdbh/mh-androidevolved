# WinMain traducido hasta los primeros fotogramas, idéntico a x86 en Windows y en el S25 — 2026-11-18

**Qué se ejecuta.** El arranque completo del juego como código traducido, sobre la capa de API del port en C (`runtime/port_api.c`):
1. la fase 2: CRT e inicializadores estáticos;
2. `WinMain(0x400000, 0, línea de órdenes, SW_SHOWDEFAULT)`, como lo llama la CRT, **hasta el tercer fotograma presentado**.

Por el camino ocurre todo esto, siempre como código traducido y sin ejecutar nada del *wrapper* de la protección:
- ventana, diálogo de vídeo y registro;
- DirectInput y Direct3D 8: dispositivo, 176 texturas y búferes;
- 30 archivos del juego leídos (1490 lecturas);
- Miles (48 voces) y Bink (una película abierta);
- bucle de mensajes y 3 escenas dibujadas.

**Código.**
- `tools/lift_winmain.py`: 1364 funciones y 85 532 instrucciones traducidas, 81 de ellas con x87 auditado, incluido el código de RenderWare de `_rwcseg`.
- `runtime/port_api.{h,c}`: las 118 API y métodos COM, con la semántica de `tools/winmain_apis.py` (`docs/WINMAIN_PORT_MODEL.md`).
- `tests/winmain_native.c` (`worksafe.test_winmain()`).

**Comparación.** Frente a la referencia de `tools/trace_static_init_x86.py --winmain` (Unicorn), estado al tercer fotograma:
- las 356 797 llamadas y el recuento de cada API y método COM;
- el reloj y los fotogramas;
- el último error;
- los CRC-32 de `.data`, `.bss`, la imagen, 64 KiB de pila, el heap global (64 MiB), el heap COM y la memoria de recursos de Direct3D (10,5 MiB);
- la palabra de control de la FPU.

**Coincide en Windows x64 y en el S25 `SM-S938B` (ARM64).** Binario ARM64 validado: `6b2975be…`. En Windows, además, el registro de llamadas (nombre y dirección de retorno de cada una) es idéntico línea a línea.

## Errores encontrados por la comparación
1. **Precisión de la FPU.** RenderWare (`0x66f404`) pone la x87 en precisión simple (`0x007F`). La referencia la respeta y la traducción calculaba en `double`: 335 valores de una tabla de senos diferían en un bit. Ahora suma, resta, multiplicación, división y raíz cuadrada redondean según el campo de precisión (`mh_x87_*_pc`), con el rango de exponente extendido de la x87. Las trascendentes no se ven afectadas, como en la x87.
2. **Instrucciones ignoradas en silencio.** PCRecomp deja algunas instrucciones como `;` con un comentario `UNIMPLEMENTED`, que el auditor no detectaba:
   - `fbld`: la conversión de texto a número de la CRT daba 0 y un archivo de configuración se leía mal;
   - `daa`: el relleno de la protección;
   - `pushf`/`popf` de 16 bits: la detección de CPU de una biblioteca, que mezcla tamaños.

   Ahora están implementadas (`recomp/x86_semantics.h`, `daa` con el algoritmo de QEMU) y cualquier otra hace abortar la traducción.
3. **`rdtsc`.** Se traducía como `__rdtsc()` del host, un resultado dependiente de la máquina. Ahora viene del port: reloj virtual × 10⁶ más el número de lecturas, igual en la referencia. El auditor rechaza cualquier llamada al host fuera de una lista cerrada.
4. **Variables locales con nombre de registro** en el arnés (`esp`, `eax` son macros de PCRecomp). Ahora el runtime se incluye antes que las cabeceras de PCRecomp.
5. **Código de `_rwcseg`.** La traza solo registraba `.text`; ahora también cubre esa sección.

La bisección (volcado de memoria en la llamada N en los dos lados) y un punto de observación de escrituras en la referencia localizaron 1 y 2 en minutos.

**Límites.** El arnés compara el estado: nada se dibuja ni suena aún. Faltan el backend OpenGL ES, el mezclador de audio, el decodificador Bink, la entrada táctil y la app que lo integre. La referencia usa el reloj virtual, el idioma inglés y ninguna entrada. Los 16 disparadores de la protección siguen sin resolver: ninguno se alcanza en este tramo.
