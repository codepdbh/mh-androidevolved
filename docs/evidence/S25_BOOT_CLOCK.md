# Prueba del reloj Android en S25

El 13 de noviembre de 2026 se compiló un programa ARM64 sintético con `win_tick.c` y `android_boot_clock.c`. Se verificó en el S25 el SHA-256 `8ed1dc2a4c04319822cf01586576d0eb43be56c70a27b9bc0b74dbeb626b4ee9`, pasó sus pruebas y se confirmó la limpieza del directorio temporal. La misma ejecución también cubrió el registro de importaciones y el PE sintético.

Las pruebas cubren conversión de segundos y nanosegundos, desbordamiento a 32 bits, rechazo de entradas inválidas y dos lecturas sucesivas del reloj de arranque Android. Esto no demuestra la resolución, precisión, época o semántica completas de Windows. No existe aún un thunk de `GetTickCount` ni una conexión con el código del juego.

En una prueba posterior se añadió un modelo sintético del retorno x86: este lee la dirección de retorno de la memoria invitada, coloca el resultado en EAX y actualiza ESP. Incluye rechazo de pila inválida y de salidas solapadas, y una llamada con reloj fallido. El ejecutable ampliado pasó en el S25 con el proveedor de reloj real; su SHA-256 fue `29721d1120350f57831a861b15b91d100ae544ea6c3cae4c9ca23a67293b814e` y la limpieza se confirmó. El modelo no está integrado en el despacho ni constituye una prueba del juego.

Después se añadió `tick_dispatch.c` y se integró en un arnés sintético del despacho comprobado de PCRecomp. Se probaron dos formas de llamada y se rechazó una dirección de retorno no autorizada; en el S25 también se usó el reloj real. El binario verificado tuvo SHA-256 `f7af033f6818e940770b2d08f6ed02738b26ed27761ff677ba7412b10bee813f`, pasó y se limpió el directorio temporal. El adaptador todavía no está registrado para llamadas reales del juego ni demuestra equivalencia completa con Windows.
