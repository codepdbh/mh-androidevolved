# Dependencias observadas

El ejecutable importa directamente `d3d8.dll`, `dinput8.dll`, `binkw32.dll` y `mss32.dll`, adem?s de bibliotecas de Windows. Esto demuestra importaciones est?ticas, no su uso efectivo ni la compatibilidad de cada funci?n. La DLL local `dinput8.dll` importa `d3d9.dll` y tiene TLS: su procedencia y funci?n est?n pendientes de investigaci?n; no asumir que es la biblioteca est?ndar de Windows. Hay que investigar tambi?n cargas din?micas. Ver `imports_report.md` y `pe_inventory.json`.
