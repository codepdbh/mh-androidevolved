# WinMain: modelo de las API del port — 2026-11-17

`tools/trace_static_init_x86.py --winmain` ejecuta en la referencia x86 (Unicorn), después de la fase 2, `WinMain(0x400000, 0, línea de órdenes, SW_SHOWDEFAULT)` igual que lo llama la CRT. Cada API de Windows que alcanza se emula en `tools/winmain_apis.py` **con la semántica que tendrá el runtime del port**. Este documento recoge las decisiones de diseño. Ninguna API se rellena con un valor inventado: lo no modelado detiene la traza con su nombre y argumentos.

## Mecanismos de la referencia

- **Callbacks síncronos:** una API puede llamar al código del juego antes de volver, como hace Windows. `CreateWindowExA` llama al `WndProc` con `WM_CREATE`, `WM_SIZE` y `WM_MOVE`; `SendMessageA` y `ShowWindow` también lo usan, y los diálogos encadenan mensajes según lo que ocurrió en el anterior. Se comprueba que el callback es stdcall.
- **COM:** objetos en memoria del invitado. La vtable apunta a direcciones falsas `0x1e10000 + 0x400·interfaz + 4·método` (hasta 256 métodos por interfaz, porque `IDirect3DDevice8` tiene 97), el mismo esquema que `runtime/d3d8.c`.
- **Funciones sustituidas (HLE):** solo una, `0x4becc0` (`GetDXVersion`). Sondea DLL de Windows (`DDRAW`, `D3D8`, `dpnhpast`, `D3D9`) y en el port devuelve `0x801`, DirectX 8.1, que es lo que implementan los shims.

## Decisiones

| Área | Modelo del port |
|---|---|
| Rutas | La carpeta elegida por SAF es `C:\Manhunt\`, y el ejecutable `C:\Manhunt\manhunt.exe`. Cada componente se resuelve sin distinguir mayúsculas (Android sí las distingue). |
| Archivos | Solo lectura sobre los datos originales. Las lecturas solapadas se completan de inmediato y señalan su evento. Las escrituras y carpetas nuevas van a una capa superpuesta: almacenamiento privado de la app en el dispositivo, memoria en la referencia. |
| Directorio actual y entorno | Empieza en la carpeta del juego y solo admite rutas dentro de ella. Las variables de entorno fijadas en tiempo de ejecución se guardan (`=C:` de `_chdir`). |
| Ventanas | Sin marco: toda la superficie de Android es área cliente. `AdjustWindowRect` no cambia el rectángulo. `CW_USEDEFAULT` sitúa la ventana en (0,0). No se envían mensajes de área no cliente. Los cambios de tamaño o posición se notifican con `WM_SIZE`/`WM_MOVE`. El primer `ShowWindow` activa la app (`WM_ACTIVATEAPP`, `WM_ACTIVATE`, `WM_SETFOCUS`). |
| Pantalla | 1280×720, el modo de escritorio del adaptador virtual. Bordes, título y menú miden 0. |
| Cursor | Posición virtual, contador de visibilidad y cursor actual. Lo alimentará la capa táctil. |
| Diálogos | El diálogo de vídeo del juego se ejecuta con controles virtuales: `WM_INITDIALOG` y después `WM_COMMAND(IDOK)` con la selección por defecto del propio juego. La interfaz Android podrá cambiar la selección antes de confirmar. |
| Registro | En memoria, vacío en la primera ejecución (como una instalación nueva). El port lo guardará en el almacenamiento de la app. |
| DirectInput 8 | Teclado y ratón del sistema (ratón de 3 ejes y 3 botones, teclado de 128 teclas) con estado a cero hasta que la capa táctil o de mando los alimente. Sin joysticks DirectInput. |
| Direct3D 8 | Un adaptador «Android OpenGL ES (Manhunt port)» con identificadores de fabricante y dispositivo a 0. Modos: 6 tamaños × X8R8G8B8/R5G6B5 a 60 Hz. **Capacidades:** clase GeForce2/GeForce4 MX, T&L por hardware, función fija, **sin shaders**, 4 texturas y 8 etapas. Texturas: formatos RGB habituales y **DXT1–5** (se descomprimen al subir si la GPU no tiene S3TC). Profundidad D16/D24S8/D24X8. Sin multimuestreo ni texturas de volumen. El dispositivo **registra** el estado (render states con los valores por defecto de DX8, etapas, transformaciones, luces, flujos) que reproducirá el backend OpenGL ES. Los búferes y texturas viven en memoria del invitado (`0x10000000`–`0x20000000`) para que el juego escriba en ellos tras `Lock`. |
| Tiempo | Referencia: reloj virtual determinista (empieza en `0x10000` ms y avanza 1 ms por consulta). Dispositivo: reloj real. |
| Idioma | Referencia: inglés de EE. UU. (`0x0409`). Dispositivo: configuración regional o ajuste de la app. |

## Recorrido hasta ahora

WinMain registra la clase y crea la ventana. Inicializa DirectInput (ratón y teclado), comprueba DirectX y crea Direct3D. Ejecuta el diálogo de vídeo, que enumera 12 modos y lee el registro. Crea el dispositivo (ventana, X8R8G8B8, D24S8) y su estado inicial (31 *render states* y 74 estados de etapa). Muestra la ventana, **lee el primer recurso real del juego** (`pictures/title/TITLE_PC.TXD`), crea texturas, hace `Reset` del dispositivo, entra en el bucle temporizado y crea `User Files`.
