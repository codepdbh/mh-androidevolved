# Candidato relacionado con Direct3D 8

En la versión identificada por `analysis/binary_versions.json`, el candidato `0x4c0830` parte de un prólogo plausible y PCRecomp recuperó 19 bloques y 84 instrucciones. Dentro de ese grafo aparece una llamada directa a `0x64408c`; el análisis de una instrucción en esa dirección encontró un salto indirecto a la entrada IAT de `d3d8.dll!Direct3DCreate8`. El candidato también contiene cuatro llamadas indirectas; todavía no se han resuelto sus destinos ni sus contratos.

El candidato y el trampolín se tradujeron a C y compilaron por separado para AArch64. Se enlazaron en un objeto ELF reubicable y se verificó que ambos símbolos están definidos. Quedan 18 símbolos externos del runtime y biblioteca C sin resolver. No se ha enlazado una implementación Direct3D, cargado el objeto, ejecutado el candidato ni validado el límite o la alcanzabilidad de la función. Esto no demuestra inicialización gráfica ni permite renderizar un fotograma.

Una segunda unidad compilada para ARM64 reúne ambas funciones con los adaptadores experimentales de memoria y despacho comprobados. El objeto contiene ambos símbolos y mantiene 20 símbolos externos, entre ellos las funciones de fallo y la resolución indirecta. Una versión x64 de esta unidad se comparó con dobles sintéticos; no se ha ejecutado en ARM64 ni con Direct3D real.

## Comparación de una ruta con dobles de prueba

Se probó en Unicorn y Windows x64 una ruta sintética que simula `Direct3DCreate8` y dos métodos COM, con cero modos disponibles y profundidades 16, 24 y 32. No se crea un dispositivo, ventana ni imagen. Los registros y flags aritméticos coincidieron inicialmente, pero la pila mostró dos diferencias: PCRecomp dejó `0xdead0000` donde x86 dejó las direcciones posteriores a las llamadas. Esta divergencia queda registrada en `private/analysis/candidate_graphics/mock_comparison_report.json`.

Se preparó una variante específica que conserva la dirección de retorno x86 en cinco sitios, calculada a partir de las instrucciones desensambladas. En esas tres pruebas, salida, registros, flags aritméticos y los 96 bytes observados de pila coinciden. La variante compiló a un objeto ARM64 reubicable con 20 símbolos externos. La corrección no es general: no se han probado otras rutas, métodos COM reales, retornos indirectos ni ARM64. Conservar direcciones reales también exige resolver correctamente cualquier retorno indirecto a ellas.

Se añadieron nueve casos sintéticos con un modo enumerado, profundidades 16, 24 y 32 y frecuencias simuladas 0, 30 y 60. La variante de retorno preciso coincide con Unicorn en registros, flags aritméticos y pila observada en los nueve casos. Estos dobles solo prueban el camino previsto: no implementan Direct3D, no prueban errores reales ni demuestran que el candidato se alcance durante el arranque.

Otros 12 casos enumeran dos modos simulados, con cuatro combinaciones de frecuencias y tres profundidades. También coinciden registros, flags aritméticos y pila observada, incluyendo rutas que iteran sobre más de un modo. No se han comparado todas las direcciones de memoria ni el comportamiento con controladores o dispositivos reales.

En una prueba sintética adicional, el doble de `Direct3DCreate8` devuelve cero. Unicorn observa una lectura no mapeada de cuatro bytes en la dirección invitada cero; la variante comprobada detiene la prueba al resolver ese mismo acceso fuera de la región sintética, que empieza en `0x10000`. No se ha comprobado todavía la política de memoria de un proceso Win32 completo ni sustituido el fallo por manejo de excepciones del juego.

El código y el informe detallado permanecen en `private/analysis/candidate_graphics/`; el trampolín está en `private/analysis/d3d8_thunk/`. El barrido que llevó a estas direcciones se describe en `analysis/import_reference_candidates.md`.
