# Autodiagnóstico y código traducido dentro de la app — 2026-11-16

**Qué se hizo.** `tools/deploy_diagnostic_app.py` ejecutó en una sesión acotada:

1. Compilación ARM64 del arnés de la candidata de tiempo (13 dependencias traducidas).
2. Validación en el S25 `SM-S938B` frente a Unicorn x86: 256 + 12 casos, NaN, comprobaciones x87 y cuatro fallos; limpieza confirmada. Se registró `validated.json` con el SHA-256 del binario (`4acdb1b726c1ec0dc49b38a5cf192fe3e4d4b8e911e06a0776bd05ffce72f75d`) y de sus salidas.
3. Librería nativa `libmh_runtime.so` (CMake, NDK 28.2) y APK de diagnóstico. La APK incluye el binario validado como `libmhae_time_test.so`; por eso es **privada** y no debe distribuirse.
4. Actualización en el teléfono con `adb install -r`. El paquete ya existía; se conservaron los datos y el permiso de la carpeta.

**Resultado en pantalla** (leído por accesibilidad tras abrir la app):

- Autodiagnóstico ARM64: memoria invitada con límites correcta; `rep movs` comprobado correcto en 1440 casos frente al modelo x86, con la copia fuera de rango rechazada sin escribir; semántica x87 correcta.
- Lectura real por descriptor SAF con la capa de solo lectura del port: 6 304 256 bytes de `manhunt.exe` en 7 lecturas de hasta 1 MiB, idénticos a los verificados por SHA-256. El fin de archivo devuelve 0 bytes, el desplazamiento a `e_lfanew` (`0x880`) es correcto y se rechaza la lectura OVERLAPPED.
- Botón «Ejecutar prueba de código traducido», pulsado mediante `input tap` en el teléfono: **CORRECTO** en 930 ms. La candidata `0x6081a0` dio salida idéntica a la validada en los 256 casos y en los 12 de la rama de argumento cero; la semántica x87 fue correcta y los fallos esperados, 4 de 4.

**Límites.** Las entradas son sintéticas y las funciones no traducidas son sustitutos. No es el arranque del juego, que sigue sin ser jugable.

**Excepción de política.** Por indicación expresa del propietario, esta sesión se ejecutó con `MHAE_OWNER_RAM_OVERRIDE=1`, que omite los umbrales de RAM libre (registrado en `logs/ram-override.log`). Mantienen su efecto los límites de memoria por proceso, la prioridad, la afinidad, los plazos y un mínimo absoluto de 512 MiB libres. La RAM libre real era de unos 1100 MiB.
