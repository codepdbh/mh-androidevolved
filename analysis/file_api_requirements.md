# Requisitos observados de apertura y cierre

El análisis estático registrado del ejecutable conocido identifica `0x81b37c` como entrada IAT de CreateFileA y `0x81b370` como CloseHandle. No demuestra alcanzabilidad desde el punto de entrada.

- La candidata `0x60fec0` primero llama a `0x60ff40`, prepara siete argumentos, fija la disposición a 3 y el modo de compartición a cero, y transmite nombre, acceso y atributos de sus tres argumentos. Guarda el handle en el objeto y devuelve si es distinto de `0xffffffff`.
- La candidata `0x60ff40` evita llamar cuando el objeto contiene `0xffffffff`; en la otra ruta llama a CloseHandle y marca el objeto inválido. La candidata `0x60feb0` la llama y devuelve la dirección del objeto.
- La ruta observada de `0x605750` transmite acceso `0x80000000` y atributos cero al envoltorio de apertura. Esto limita lo observado a lectura; no permite asumir las necesidades de otras rutas del juego.

En Win32, disposición 3 corresponde a abrir un archivo existente, y compartir cero tiene restricciones de exclusividad; ver [CreateFileA](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilea). Cerrar handles y comunicar los errores también requiere semántica específica; ver [CloseHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-closehandle).

La tabla POSIX implementada actualmente es un proveedor interno. No reproduce todavía los modos de compartición Win32, GetLastError, conversión de nombres ANSI o mayúsculas, ni la resolución mediante SAF. Por ello no debe registrarse como implementación completa de CreateFileA. La tabla y los tres envoltorios ya pasaron una prueba real en el S25 con adaptadores específicos del arnés, limitados a los argumentos observados de solo lectura; ver `docs/evidence/S25_READONLY_HANDLES.md`. Falta completar las políticas generales e integrarlas en la aplicación.
