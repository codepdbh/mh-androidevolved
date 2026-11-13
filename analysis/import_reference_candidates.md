# Candidatos de referencias a importaciones

Un barrido acotado de patrones de bytes en `.text`, comprobados mediante Capstone al inicio de cada patrón, encontró 343 referencias candidatas a entradas IAT y 93 posibles llamadas a trampolines de importación. Son hipótesis: no se han demostrado los límites reales de instrucciones ni la alcanzabilidad. El detalle está en `private/analysis/import_reference_candidates.json`.

Para Direct3DCreate8 aparece un posible trampolín en `0x64408c` y posibles llamadas en `0x4c0840` y `0x63f582`; para DirectInput8Create, un posible trampolín en `0x644098` y una llamada en `0x4c1bc9`. Para BinkOpen aparece una posible llamada indirecta en `0x4c0cfa`. Deben analizarse dentro de funciones confirmadas antes de atribuirles un papel de inicialización o reproducción.
