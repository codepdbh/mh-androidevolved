# Candidato relacionado con DirectInput 8

Una referencia estática sugiere un inicio en `0x4c1ba0`. PCRecomp recuperó cuatro bloques y 28 instrucciones, incluidas llamadas candidatas a `GetModuleHandleA`, al trampolín de `DirectInput8Create` y a `0x60f110`. El inicio y la alcanzabilidad siguen siendo hipótesis; no se han identificado asignaciones de gameplay.

El candidato y el trampolín `0x644098` se tradujeron y compilaron por separado, y se enlazaron como objeto reubicable AArch64. Se verificó que ambos símbolos están definidos; quedan 17 externos, incluido `sub_0060F110` y las funciones de despacho. Los artefactos derivados están en `private/analysis/candidate_input/` y `private/analysis/dinput8_thunk/`. No se ha enlazado DirectInput ni ejecutado esa unidad AArch64; esto no demuestra entrada funcional.

Una variante limitada sustituye tres llamadas por otras que conservan sus direcciones de retorno x86 y utiliza los adaptadores de memoria y despacho comprobados. Compiló como objeto AArch64. Una comparación en Windows x64 con dobles sintéticos de Win32 y DirectInput coincidió con Unicorn en registros, flags aritméticos, pila y configuración para éxito, fallo y estado ya inicializado. No se capturó entrada real. Esto no verifica DirectInput, el mapeo de acciones ni la ejecución en ARM64.
