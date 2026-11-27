# Manhunt: Android Evolved

Proyecto experimental para llevar Manhunt PC a Android ARM64 mediante recompilación estática. El código x86 del juego se traduce a C, se compila para ARM64 y se ejecuta sobre un runtime propio. El runtime emula Win32, Direct3D 8 (sobre OpenGL ES 3), DirectInput, Miles y Bink.

**Estado (27-11-2026):** en un Galaxy S25 Ultra funcionan el menú, las cinemáticas y el primer nivel, a 65–74 fps, con controles táctiles. Fuera de los recorridos validados el juego puede detenerse en funciones aún no traducidas. Detalles en [estado vigente](docs/CURRENT_STATE.md), [problemas conocidos](docs/KNOWN_ISSUES.md) e [historial](docs/STATUS.md).

## Qué hay en este repositorio y qué no

- **Sí está:** runtime, renderers, herramientas de traducción y validación, launcher Android y documentación.
- **No está:** la copia del juego, el código traducido, las bibliotecas, la APK ni las capturas con contenido del juego. Son locales y privados, porque proceden del ejecutable comercial del usuario. Hace falta una copia legítima propia para generarlos.
- **Seguridad del entorno de trabajo:** el juego original no se ejecuta en el PC. Toda ejecución pasa por `scripts/worksafe.py`. Ver [política de trabajo seguro](docs/WORK_SAFE_POLICY.md).

## Licencias de terceros

- `runtime/bink_decoder.c` y `runtime/bink_tables.h` derivan del decodificador Bink de FFmpeg. Igual que el original, están bajo la **GNU LGPL 2.1 o posterior**: <https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html>.
- La traducción usa PCRecomp en una revisión fijada, según `docs/`.

## Herramientas

- Inventario estático (requiere Python y `pefile`): `python tools/pe_inventory.py "Manhunt Collection/Manhunt"`. No ejecuta los archivos examinados.
- Pruebas del supervisor: `python tests/test_worksafe.py`.
