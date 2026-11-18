# Primera imagen del juego, dibujada desde el código traducido — 2026-11-18

`runtime/sw_renderer.c` es un rasterizador de referencia en C portable, sin GPU. Recibe las notificaciones del dispositivo Direct3D 8 del port (`Clear`, cada dibujo, `Present`) y lee su estado registrado: formato FVF, vértices e índices en memoria del invitado, transformaciones y viewport, texturas, combinación de la etapa 0, prueba alfa, mezcla, z-buffer y *culling*. El dispositivo no cambia su comportamiento, así que la comparación con x86 sigue siendo exacta.

Con `MH_RENDER=<carpeta>`, `tests/winmain_native.c` guarda cada fotograma presentado como PNG y registra cada dibujo.

**Resultado.** El fotograma 1 es la **pantalla de títulos y avisos legales de Manhunt**: logotipo, logos de Rockstar y créditos de Bink y Miles. La imagen queda en `private/evidence/first_frame_title_legal.png`; no se publica porque es contenido del juego.

El juego la cargó de `pictures/title/TITLE_PC.TXD`, la subió a una textura `X8R8G8B8` de 512×512 y dibujó un rectángulo ya transformado (`XYZRHW|DIFFUSE|TEX1`, 2 triángulos, mezcla alfa `SRCALPHA/INVSRCALPHA`, prueba alfa), todo como código traducido.

El fotograma 3 es el primero del vídeo de introducción (Bink) y sale negro hasta que exista el decodificador.

**Siguiente.** El backend OpenGL ES en la app del S25, contrastado con este rasterizador; después, el decodificador Bink, el audio y la entrada.
