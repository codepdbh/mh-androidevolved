# Primera imagen del juego, dibujada desde el código traducido — 2026-11-18

`runtime/sw_renderer.c` es un rasterizador de referencia en C portable, sin GPU. Recibe las notificaciones del dispositivo Direct3D 8 del port (`Clear`, cada dibujo, `Present`) y lee su estado registrado: formato FVF, vértices e índices en memoria del invitado, transformaciones y viewport, texturas, combinación de la etapa 0, prueba alfa, mezcla, z-buffer y *culling*. El dispositivo no cambia su comportamiento, así que la comparación con x86 sigue siendo exacta.

Con `MH_RENDER=<carpeta>`, `tests/winmain_native.c` guarda cada fotograma presentado como PNG y registra cada dibujo.

**Resultado.** El fotograma 1 es la **pantalla de títulos y avisos legales de Manhunt**: logotipo, logos de Rockstar y créditos de Bink y Miles. La imagen queda en `private/evidence/first_frame_title_legal.png`; no se publica porque es contenido del juego.

El juego la cargó de `pictures/title/TITLE_PC.TXD`, la subió a una textura `X8R8G8B8` de 512×512 y dibujó un rectángulo ya transformado (`XYZRHW|DIFFUSE|TEX1`, 2 triángulos, mezcla alfa `SRCALPHA/INVSRCALPHA`, prueba alfa), todo como código traducido.

El fotograma 3 es el primero del vídeo de introducción (Bink) y sale negro hasta que exista el decodificador.

**Siguiente.** El backend OpenGL ES en la app del S25, contrastado con este rasterizador; después, el decodificador Bink, el audio y la entrada.

## En el S25, dentro de la app — 2026-11-18

`runtime/gles_renderer.c` es el backend OpenGL ES 3. Comparte con el rasterizador de referencia el montaje de vértices, la decodificación de texturas y el estado de píxel (`runtime/d3d_common.c`). La combinación de la etapa 0 y la prueba alfa van en el *fragment shader*; la mezcla y la profundidad usan las funciones fijas de GL; el *culling* se decide en la CPU como en la referencia. El back buffer es un framebuffer fuera de pantalla que se escala a la ventana conservando la proporción.

`android/app/src/main/cpp/game_jni.c` crea un hilo con pila de 256 MiB y un contexto EGL/GLES 3 sobre la `Surface` de `GameActivity`, y ejecuta el mismo arranque compartido que el arnés de comparación (`runtime/game_runner.c`). `GameActivity` ocupa toda la pantalla en horizontal y corre en un proceso propio (`:game`); lee la copia del usuario en `/sdcard/mh-androidevolved`, con acceso a todos los archivos. `scripts/worksafe.py build_game_library` compila `libmh_game.so` de forma privada, solo a partir de la unidad validada en el S25, y `build_diagnostic_apk` la incluye. Entonces se activa el botón «Jugar».

**Prueba.** En el S25 (Adreno 830, OpenGL ES 3.2), el juego recorrió el arranque traducido hasta 2 fotogramas en unos 170 ms y presentó la **pantalla de títulos y avisos legales** a pantalla completa. La captura está en `private/evidence/s25_title_gles.png`, que no se publica. En el host, la comparación con x86 sigue siendo exacta tras añadir el reloj opcional.

**Límites actuales.**
- La app usa el reloj virtual y se detiene en el fotograma 2. El código traducido solo cubre lo que se trazó (3 fotogramas); más allá habría saltos a código sin traducir.
- `mh_port_set_clock` ya ofrece tiempo real para cuando se amplíe la cobertura.

**Siguiente.** Ampliar la traza y el código traducido más allá de la introducción (Bink, menú principal), con entrada táctil y audio.

## Intro saltada y menú principal en el S25 — 2026-11-18

- **Entrada guionizada.** La referencia x86 y el port aplican el mismo guion de entrada (`MH_KEYS="clave:desde:hasta"`: código DIK, o `100`+n para el botón n del ratón, pulsado mientras `desde ≤ fotogramas presentados < hasta`). El bucle del vídeo de introducción solo lee el ratón (`DIMOUSESTATE2`) y salta tras más de 1 s con un clic; el guion `100:30:34` lo hace.
- **Lo que el juego pidió después**, implementado igual en `tools/winmain_apis.py` y `runtime/port_api.c`:
  - memoria de recursos Direct3D reutilizable al liberar texturas, superficies y búferes (lista libre, primer hueco, coalescencia; antes se agotaba en el fotograma ~250 del vídeo);
  - `AIL_process_digital_audio`: descompresión IMA ADPCM (mono, 4 bits) a PCM de 16 bits;
  - `GetModuleHandleA("kernel32.dll")`, `GetProcAddress` y `GetDiskFreeSpaceExA`, para la comprobación de espacio de las partidas.
- **Traducción.** Referencia x86 de 300 fotogramas (631 678 llamadas). La unidad crece a 1607 funciones y 108 961 instrucciones. La detección del límite de las tablas de saltos acepta ahora instrucciones x87 entre `cmp` y `ja`.
- **Pruebas.** Idéntico a x86 en Windows x64 y en el S25: llamadas, memorias, FPU y reloj. El fotograma 296 es el **menú principal** (`private/evidence/main_menu_frame296.png`).
- **App.** Sin límite de fotogramas y con el mismo clic de la referencia, la app salta la intro y muestra el menú principal animado en el S25 (`private/evidence/s25_menu.png`). Si el juego llega a código aún no traducido, el hilo se detiene y el último fotograma queda en pantalla.
- **Siguiente.** Trazar la navegación del menú (PLAY, carga del primer nivel) con el guion de entrada.

## Idioma del juego — 2026-11-18

- **Cómo elige el idioma el juego.** Toma el idioma principal de `GetUserDefaultLangID` (función 0x604e50): francés 0x040c, italiano 0x0410, español 0x0c0a y alemán solo de fuera de Alemania (0x0c07, 0x0807). Con 0x0407 cae a inglés, igual que con cualquier otro idioma. Tu copia trae los cinco textos (`levels/GLOBAL/PC_TEXT/pc_game*.gxt`).
- **Port.** `mh_port_set_language` y `mh_game_config.langid`, con `MH_LANG` en la referencia y en el arnés.
- **App.** Selector bajo «Jugar» (English, Español, Français, Deutsch, Italiano). Por defecto toma el idioma del teléfono y recuerda la elección.
- **Escenarios.** `MH_SCENARIO=<nombre>` escribe la traza y la referencia en `winmain/scenarios/<nombre>/`. `tools/lift_winmain.py` traduce la unión de todos los escenarios, y `test_winmain` compara cada uno en Windows y en el S25. Hay trazas del menú en los cuatro idiomas además del inglés, hasta el fotograma 300.
- **Teclado de los menús.** El menú no lee el teclado por DirectInput: lo recibe en `WM_KEYDOWN`/`WM_CHAR`. En cada `Present`, la referencia y el port encolan los cambios del estado de teclado (guion y teclas en vivo de la app) como mensajes para la ventana con foco.
- **Prueba.** En el S25, la app con «Español» muestra el **MENÚ PRINCIPAL en español** (`private/evidence/s25_menu_es.png`).
