# Problemas conocidos (27-11-2026)

## Visibles en el juego

- **Vídeos Bink en negro.** `BinkOpen`, `BinkWait`, `BinkNextFrame` y el resto se emulan con la duración real de cada vídeo, pero sin decodificar: los 21 vídeos (Bink 1, 512×512, con audio) se ven en negro y sin sonido. Afecta a las introducciones y finales de nivel y a los títulos.
- **El HUD queda bajo los controles táctiles.** En modo panorámico las barras, la silueta y el radar caen en la esquina inferior derecha, debajo de los botones.
- **Iluminación sin referencia directa.** Están implementadas las luces puntuales, direccionales y de foco por vértice, la etapa de textura 1, la generación de coordenadas en espacio de cámara y la niebla. No se ha podido comparar con el juego original en PC: las reglas del proyecto impiden ejecutarlo.
- **Funciones aún no implementadas en los renderers:**
  - stencil;
  - etapas de textura 2 y siguientes;
  - mipmaps, de los que solo se usa el nivel 0;
  - luz especular (`D3DRS_SPECULARENABLE`);
  - puntos y líneas no pretransformados;
  - borde de color de `D3DTADDRESS_BORDER`, que se trata como CLAMP.
- **El renderer de referencia por software** (`runtime/sw_renderer.c`, solo para diagnóstico en PC) no tiene niebla ni etapa 1.

## Cobertura y validación

- La validación compara 18 escenarios (menús en cuatro idiomas, controles, partes del primer nivel y guardado) con la ejecución x86 de referencia. Fuera de esos recorridos no hay garantía de equivalencia. Si se llega a una función no traducida, el juego se detiene de forma controlada.
- El reloj en tiempo real (opción del launcher) es más fluido, pero queda fuera de los recorridos validados, que usan el reloj virtual.
- La FPU se modela con `double`: no hay precisión extendida de 80 bits. Se emula el control de precisión de 24 bits.
- Tras `IMUL`, Intel no define SF/ZF/AF/PF. Si algún código dependiera de esas banderas, la traducción no garantizaría el valor del hardware real.
- El código traducido corre en un solo hilo del host. Los accesos a memoria del juego no son `volatile`, lo que es correcto solo con un hilo. `MH_RECOMP_VOLATILE_MEMORY` restaura los accesos `volatile`.

## Historial

- El bloqueo de arranque por protección, documentado en `BOOT_PROTECTION_BLOCKER.md`, ya no impide ejecutar el juego.
- Los problemas antiguos de verificación ARM64, NaN x87 y `fdivp` que figuraban aquí se resolvieron en sesiones anteriores; están en `STATUS.md`.
