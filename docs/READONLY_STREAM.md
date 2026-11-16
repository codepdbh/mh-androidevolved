# Lectura real de solo lectura

`runtime/readonly_stream.c` proporciona un backend POSIX/Android acotado para archivos regulares abiertos en modo solo lectura. Acepta un descriptor prestado, comprueba su modo, duplica el descriptor y mantiene su propia posición mediante `pread`. No abre rutas, no escribe ni cambia la posición del descriptor prestado. El llamador conserva la responsabilidad de serializar accesos y de no alterar sus metadatos.

La lectura hacia memoria invitada valida el rango y el contador, limita una petición a 1 MiB y utiliza un búfer temporal. El destino y la posición solo se actualizan si la lectura tiene éxito. El proveedor rechaza salidas superpuestas, operaciones OVERLAPPED, archivos no regulares y descriptores con permiso de escritura. Devuelve estados propios, no códigos de GetLastError; todavía no existe una tabla general de handles ni una implementación completa de Win32.

La interfaz síncrona de ReadFile usa la posición del archivo y un contador de bytes; los detalles y los casos adicionales están en la [documentación oficial de ReadFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-readfile). Este proveedor implementa solo el subconjunto descrito aquí.

`tests/time_readonly_stream_native.c` conecta el envoltorio traducido `0x60ff60` al proveedor, con un único handle de prueba. Comprueba lectura consecutiva, retorno parcial al final, EOF, petición vacía, posición independiente, vida del descriptor duplicado y rechazos. Luego lee únicamente las cabeceras DOS/PE de la copia conocida en el S25. El perfil supervisado comprueba hashes antes y después y elimina exactamente su binario y archivo temporal.

Estado verificado: el backend compiló para ARM64 con `-Wall -Wextra -Werror` y el recorrido completo pasó en el S25, incluyendo lecturas reales del archivo temporal y de las cabeceras de la copia del juego. Se confirmaron los hashes sin cambios y la limpieza. Ver `evidence/S25_REAL_READONLY_STREAM.md`. La apertura de archivos por nombre, la tabla de handles, los errores Win32 y la integración general en el juego siguen pendientes.
