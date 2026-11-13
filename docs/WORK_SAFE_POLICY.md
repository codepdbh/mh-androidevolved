# Política de trabajo seguro

No se ejecutan el juego original, instaladores ni programas con interfaz. No se alteran pantalla, foco, entrada ni archivos originales. Las ventanas de prueba están bloqueadas hasta disponer de un host seguro.

El supervisor inicia procesos suspendidos y sin consola, los asigna a un Job Object y solo después los reanuda. El trabajo limita memoria total, afinidad, prioridad y número de procesos; al vencer el plazo se cierra el trabajo completo. Los perfiles permitidos están restringidos a pruebas propias y a comandos fijos de compilación Android o comprobación Java. Gradle se ejecutaría sin red y con un trabajador. Antes de iniciar se exige memoria libre suficiente. Una prueba confirma que un descendiente termina al vencer el plazo.

El perfil de dispositivo autorizado admite dos pruebas ARM64 propias y, en un perfil separado, una prueba sintética de despacho, únicamente en un Galaxy S25 identificado por ADB. Verifica los hashes antes de ejecutar y utiliza un directorio temporal único; la limpieza apunta exclusivamente a los archivos seleccionados y ese directorio. Exige 1536 MiB libres al iniciar y detiene las operaciones si bajan de 1024 MiB; intenta la limpieza exacta incluso bajo presión. Se comprobó el rechazo y limpieza con ADB simulado; las dos primeras pruebas pasaron en un S25 Ultra real. La prueba de despacho aún no se ha ejecutado en el teléfono.

Para reducir reinicios de ADB se preparó una variante de despacho que transfiere el binario y realiza las comprobaciones y limpieza en una sola sesión. El script se valida sintácticamente antes de enviarlo y registra si la limpieza pudo confirmarse. La variante ha pasado pruebas simuladas; todavía no se ha ejecutado en el dispositivo. Si se interrumpe una creación y no hay confirmación de propiedad, no se borra un directorio desconocido.

No se mide ni adapta dinámicamente la presión de memoria durante una compilación. El árbol real de Gradle todavía no se ha probado. Un Job Object y CREATE_NO_WINDOW no impiden que un programa arbitrario abra ventanas o cambie la pantalla: no son una caja de seguridad. Las restricciones solo alcanzan a procesos lanzados por este supervisor y no se han validado pruebas gráficas.

Referencia conceptual, sin copiar código: https://github.com/codepdbh/hitman2-android-evolved/blob/main/scripts/worksafe.py.
