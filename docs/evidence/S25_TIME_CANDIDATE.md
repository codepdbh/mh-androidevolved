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
