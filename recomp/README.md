# Preparación de PCRecomp

Se preparó una copia local privada de las herramientas y el runtime de PCRecomp en la revisión `93a74327f33d399d2bf4ee606c7a72388c193617`. El archivo de origen descargado tenía SHA-256 `b9ae8e7b584af8695b5c85ed9ab2e1fc0fc7c5838d0c5a9e30ed4810e4832721`. Se usaron sus módulos de análisis PE y desensamblado para una ventana de 128 bytes en el punto de entrada; el resultado está en `private/analysis/entrypoint.json`. Un candidato heurístico de 19 instrucciones en `.text` se tradujo a C y compiló por separado para ARM64: `private/analysis/candidate/`. No se ha demostrado que el candidato sea una función alcanzable, ni se ha enlazado o probado. Usa `rdtsc`; el runtime de referencia lo sustituye por tiempo monotónico en nanosegundos sobre ARM, lo cual no demuestra equivalencia de frecuencia ni comportamiento. Según el [README del proyecto](https://github.com/sp00nznet/pcrecomp), `lift32.py` es una biblioteca y el flujo de 32 bits se invoca a través de `python -m tools`. Hay modelos con registros globales y con estructura explícita de CPU; falta estudiar su correspondencia con este runtime, memoria, importaciones, saltos indirectos, TLS y excepciones.

PCRecomp publica una [licencia MIT](https://github.com/sp00nznet/pcrecomp/blob/main/LICENSE). La revisión utilizada está fijada arriba; se debe auditar cada componente y conservar los avisos antes de reutilizarlo. El código generado a partir del juego se mantendrá privado; no se deben utilizar herramientas de evasión de protecciones. No se ha determinado la compatibilidad completa de la versión local ni se ha levantado el juego completo.

## Segundo candidato y prueba diferencial

Un segundo candidato heurístico en `0x40a020` contiene 51 instrucciones, sin llamadas externas ni instrucciones de reloj. PCRecomp generó C y Clang produjo un objeto ARM64; no se ha enlazado al juego ni ejecutado en un dispositivo. Con Unicorn se ejecutó el candidato x86 aislado sobre 167 entradas sintéticas, sin iniciar el PE como programa. Después el C generado se compiló a WebAssembly usando macros simplificadas de prueba: coincidieron el valor de salida, ocho registros generales, 36 bytes de pila, el objeto y la tabla sintéticos, y los seis flags aritméticos.

La misma comparación pasó también compilando y ejecutando el C generado en Windows x64 con el encabezado `recomp_types.h` real de PCRecomp y memoria sintética, sin interfaz gráfica. El primer intento de compilación falló al no poder iniciar el enlazador con el límite de dos procesos; con cuatro procesos y 512 MiB por trabajo se completó bajo el supervisor. Estas pruebas no comparan toda la memoria ni otros flags y no demuestran equivalencia general, alcanzabilidad en el juego, ni funcionamiento en ARM64. Los artefactos derivados permanecen en `private/analysis/candidate_deterministic/`.

El modelo de memoria `recomp32` utiliza `g_mem_base` y macros que producen punteros del host. Hay un adaptador experimental de acceso acotado para el candidato, probado en 653 casos con cuatro alineaciones y compilado sin enlazar para ARM64. Soporta las desalineaciones de esos casos en Windows x64 y rechaza accesos fuera de rango, pero no cubre todas las formas de acceso de PCRecomp ni se ha ejecutado en ARM64; no es integración completa del runtime. Véase `docs/ARCHITECTURE.md`.

## Candidato x87

El candidato heurístico `0x409960` contiene 60 instrucciones, incluidas operaciones x87. Su C se compiló a ARM64. Para una variante de prueba con memoria comprobada se sustituyeron tres lecturas flotantes concretas por `MEMF`, tras verificar el hash y la forma exacta del C generado; también compiló para ARM64, sin enlazarse ni ejecutarse en el dispositivo.

En Windows x64, la variante con el encabezado real de PCRecomp y el adaptador coincidió con Unicorn en 653 casos de números finitos y 288 de valores especiales (cero negativo, infinitos y NaN). Se compararon resultado, registros generales, seis flags aritméticos, pila y memoria observada, además de la profundidad final de la pila x87. No se compararon los flags de excepción ni el estado completo x87, y no se ha establecido alcanzabilidad ni equivalencia general. Los artefactos permanecen en `private/analysis/candidate_x87/`.

## Candidato gráfico

Un candidato relacionado con `Direct3DCreate8` y su trampolín de importación se levantaron y compilaron a ARM64, y se enlazaron juntos en un objeto reubicable. Quedan 18 símbolos externos sin resolver y las llamadas indirectas no se han implementado ni probado. No hay inicialización gráfica funcional; ver `analysis/graphics_candidate.md`.

Las referencias Hitman 2 y Max Payne 2 necesitan una revisión de licencia por componente antes de copiar código; las rutas `LICENSE` consultadas en la raíz no devolvieron un archivo. La ausencia de ese archivo no determina por sí sola el estado legal del repositorio completo.
