# Pruebas sintéticas en Galaxy S25 Ultra

Fecha: 2026-11-13. Modelo informado por Android: `SM-S938B`; ABI: `arm64-v8a`.

El supervisor `scripts/worksafe.py` copió dos ejecutables propios a un directorio temporal único, verificó su SHA-256 en el dispositivo, los ejecutó y eliminó ambos archivos y el directorio. Ambos terminaron con código 0:

- `guest_memory_test`: SHA-256 `4ddc5b88e3cbaeaae8954bfd67c6c8c64e58f4a023180839bfa553b759ad390a`.
- `pe32_test`: SHA-256 `bef5334ceed052fd367f4bda91010b0ccd7a6b902097536716260f90e1bd7084`.

Las pruebas usan datos sintéticos y cubren memoria, mapeo PE e importaciones. No se copiaron archivos comerciales ni se instaló una APK. No prueban el arranque del juego, el renderer, audio, controles ni la biblioteca JNI en Android. Los registros locales están en `logs/device-*` y se mantienen fuera del repositorio.

Reproducción con un solo Galaxy S25 autorizado y los binarios verificados existentes: `python -c "import sys; sys.path.insert(0,'scripts'); import worksafe; print(worksafe.run_android_device_tests())"`. El supervisor identifica modelo y ABI y verifica los hashes antes de ejecutar; si se regeneran los binarios, sus hashes pueden cambiar.
