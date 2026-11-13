# Candidata de tiempo en ARM64 sobre S25 — 2026-11-13

**Qué se hizo.** El arnés aislado `tests/time_candidate_native.c` se compiló con el NDK 28.2 (`aarch64-linux-android29`, `-O0`, PIE) junto con la candidata `0x6081a0` y sus seis dependencias traducidas (`-DMH_REAL_SMALL_DEPS`), mediante `build_time_candidate_arm64_test()`. El binario resultante contiene código derivado del juego y permanece en `private/analysis/candidate_time/android/`; no se publica.

- SHA-256 del binario: `6d6998baa14dedf9adb8d1c8d6b5a469abd807a1b656e684e1594b8e664e12d3` (32 024 bytes, ELF64 AArch64 PIE comprobado).
- SHA-256 del arnés usado: `900e2df879973d3ccb0a0f3d8a6196959d04077d9a24d0231478f694a3273f8c`.

**Ejecución.** `run_time_candidate_on_s25()` abrió una única sesión ADB en un Galaxy S25 Ultra `SM-S938B`: comprobó modelo y ABI, creó un directorio aleatorio en `/data/local/tmp`, verificó el hash en el dispositivo, ejecutó los casos y eliminó exactamente ese archivo y directorio (`MHAE_CLEANUP_OK`). No se tocó ninguna APK ni archivo del juego y no se usó la interfaz.

**Resultados.**

| Prueba | Resultado |
| --- | --- |
| 256 casos principales (4 relojes × 4 escenarios × 4 alineaciones × 4 modos) | Coinciden con la referencia x86 de Unicorn |
| 12 casos de la rama de argumento cero | Coinciden con la referencia x86 |
| Objeto nulo / temporizador ausente / destino virtual ausente / objeto virtual nulo | Códigos de salida 70 / 74 / 75 / 71, los mismos que en Windows x64 |

Se compararon en el PC los registros generales, seis banderas aritméticas, pila observada, prefijo del objeto, búfer copiado y estado global y de reloj (`tests/compare_time_native.py` y `tests/compare_time_indirect_zero.py` con la plataforma `android-arm64`).

**Límites.** Las dependencias restantes, la tabla virtual, el temporizador y las API son sustitutos sintéticos. Es la primera ejecución en ARM64 de código traducido del juego, pero no demuestra equivalencia general, no está integrada en la APK ni en un runtime y el juego sigue sin arrancar. Los fallos se comparan solo por código de salida; el rechazo del destino ocurre antes de apilar el retorno y no reproduce todo el estado de excepción x86.

## Segunda ejecución: séptima dependencia

Se añadió la traducción del selector de modo `0x5daa20` (`tools/lift_time_branch_dependency.py`). Elige según `[0x7d6b18]` entre llamar a `0x476a80`, a `0x476aa0` o a ninguna. En ambos lados el global toma 0, 1, 2 o el valor de patrón anterior según la alineación, y las dos funciones llamadas son contadores sintéticos (`branch_calls`). En el escenario que alcanza el selector, 16 casos llaman a la primera, 16 a la segunda y 32 a ninguna.

- SHA-256 del binario ARM64: `aff80538e1fe9ed4e4d2df6f9880198ea3035beb977b89b06d52c9c22061614a`.
- Resultado en el S25 `SM-S938B`: 256 casos principales y 12 de argumento cero coinciden con Unicorn; los cuatro fallos devolvieron 70 / 74 / 75 / 71; limpieza confirmada. La comparación en Windows x64 también coincidió.

## Tercera ejecución: copias de búfer

Se tradujeron `0x481340` y su rutina de copia `0x611640` (`tools/lift_time_memcpy_dependency.py`); los tres `rep movs` usan el helper comprobado `mh_recomp_rep_movs`. Según el índice de reloj, el arnés configura ningún objeto, solo A (7 bytes a destino desalineado, ruta de bytes), solo B (35 bytes, ruta de alineación más palabras) o ambos (64 y 49 bytes). Se compara además la región destino (`copy_out_hex`).

- SHA-256 del binario ARM64: `3240db25e5ad249d2aab024af14de002c9bece3b1d1c59a1bcfa3aba8a1f70b0`.
- Resultado en el S25 `SM-S938B`: 256 + 12 casos coinciden con Unicorn; fallos 70 / 74 / 75 / 71; limpieza confirmada. Windows x64 también coincidió.

## Cuarta ejecución: sonda de pila

Se tradujo `0x648540`, que redondea `eax` a múltiplo de cuatro y continúa en `0x648500`: toca cada página de 4 KiB, baja `esp`, restaura `edx` y vuelve con `eax` igual al nuevo `esp`. El relleno `lea eax,[eax]` de `0x64851c` es inalcanzable y no se traduce. Antes se usaba un doble que perdía `edx` y no dejaba en la pila las palabras que escribe el original.

- SHA-256 del binario ARM64: `f55e6a33e101df70601cebb845d34cc00cdb4dd6133029c29867f2b8ee0f830e`.
- Resultado en el S25 `SM-S938B`: 256 + 12 casos coinciden con Unicorn; fallos 70 / 74 / 75 / 71; limpieza confirmada. Windows x64 también coincidió.
- Límite: las páginas de guarda de Windows no se modelan; los toques de página son accesos comprobados normales.

## Quinta ejecución: dependencia x87

Se tradujeron `0x5daa50` y `0x5ea2b0` con dos reescrituras auditadas: cinco accesos `*(float*)ADDR` a `MEMF` y la división de `fdivp` a IEEE. Según `mode`, las entradas flotantes son valores simples, divisor cero en la segunda división, valores negativos e inexactos, o divisores cero en ambas. Se comparan los dos flotantes resultantes por patrón de bits, el argumento y las llamadas a los dobles de `0x5db0d0` y `0x482f20`, y la profundidad final de la pila x87.

- SHA-256 del binario ARM64: `7ee1d5cceb0a7131c533f143dcab798b7e8d8044d8b8002602243de242892056`.
- Resultado en el S25 `SM-S938B`: 256 + 12 casos coinciden con Unicorn, incluidos `-inf` en ambas divisiones; fallos 70 / 74 / 75 / 71; limpieza confirmada. Windows x64 también coincidió.
- Límites: no se generó ningún NaN; no se modelan la precisión extendida, los flags de estado ni las excepciones x87.
