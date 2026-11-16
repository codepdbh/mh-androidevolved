# Apertura relativa e identificadores de archivo

`runtime/readonly_handles.c` amplía el proveedor de lectura con una tabla limitada a 16 archivos. Cada identificador incluye el número de casilla y una generación; cerrar un archivo cambia su generación. Al agotar las generaciones la casilla se retira en vez de reciclar identificadores antiguos. Cerrar y volver a vincular la carpeta conserva esas generaciones.

La carpeta autorizada se aporta como descriptor de directorio de solo lectura y se duplica. Las rutas se validan enteras antes de abrir componentes mediante `openat`, con rechazo de enlaces simbólicos y apertura no bloqueante para no quedarse esperando en una FIFO. El último componente debe ser un archivo regular de solo lectura. Los descriptores y sus posiciones son independientes.

El analizador portátil `readonly_path.c` admite separadores slash y backslash y nombres exactos. Rechaza rutas absolutas, prefijos de unidad, dos puntos, controles, componentes vacíos, `.` y `..`, componentes mayores de 255 bytes y rutas mayores de 1023 bytes. No implementa conversión de caracteres ni comparación de nombres sin distinción de mayúsculas. La tabla no es una API Win32 completa: sus estados son propios, necesita serialización del llamador y no soporta mutaciones concurrentes del árbol. La vinculación de un directorio POSIX no equivale al permiso SAF de la aplicación; queda pendiente el proveedor de documentos Android.

## Verificación actual

- La tabla y el analizador compilaron por separado para ARM64 con `-Wall -Wextra -Werror`.
- Las pruebas del analizador pasaron en Windows: rutas permitidas y rechazadas, límites, salidas sin cambios en error y entrada/salida superpuestas.
- El arnés `tests/time_file_handles_native.c` pasó en el S25 con lectura de dos archivos, cursores independientes, identificadores caducados, capacidad, retirada por desbordamiento, rutas rechazadas, enlaces y cabeceras de la copia del juego. La prueba de FIFO quedó excluida porque Android denegó crearla; no se cambió esa protección.
- Después se añadieron tres envoltorios traducidos de apertura/cierre y pasó el recorrido completo abrir/leer/cerrar, con adaptadores de API de prueba limitados al modo de lectura observado. Ver `evidence/S25_READONLY_HANDLES.md` para el hash, los resultados y las limitaciones.
- Después se reconstruyó el arnés actualizado con validación portátil y retirada de identificadores al agotar generaciones; el ELF64 ARM64 compiló con SHA-256 `03936a04c4d3c395ea0af091d2d4b728df3e72851092ff0855acfc129adfb280`. Esta reconstrucción fue solo compilación y tampoco ejecutó el arnés en el teléfono.

La nota de reconstrucción anterior corresponde al intento sin conexión; la ejecución posterior sí está documentada en la evidencia enlazada.

Al volver a estar disponible el teléfono, `python tools/validate_readonly_stream.py --handles` construye y ejecuta la prueba en una sesión acotada. Crea únicamente su carpeta temporal propia, comprueba los hashes de los archivos y elimina exactamente sus archivos, enlaces y subdirectorio. `--handles-build` solo compila y no ejecuta en el teléfono.
