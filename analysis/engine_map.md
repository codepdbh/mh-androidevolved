# Mapa del motor

La imagen principal es PE x86 (0x14c), importa Direct3D 8, DirectInput 8, Bink y Miles. Esto no identifica todav?a funciones concretas del motor ni acredita RenderWare. Pendientes: motor y recursos, inicializaci?n, audio y v?deo, niveles, scripts, guardado, controles y temporizaci?n. No hay direcciones ni rutas de arranque verificadas. Prioridad: arranque, archivos, gr?ficos, audio, entrada, men? y primera escena.

## Importaciones concretas

La tabla del ejecutable contiene `Direct3DCreate8` y `DirectInput8Create`; el resto de operaciones COM no se identifica simplemente mediante esas importaciones. Bink incluye apertura, decodificaci?n y avance de fotogramas, y selecci?n del sistema Miles. Miles incluye interfaces de audio 3D, volumen, posici?n, distancia y oclusi?n. Estas son funciones importadas, no prueba de su ejecuci?n efectiva.
