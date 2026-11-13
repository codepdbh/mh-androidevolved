# Manhunt: Android Evolved

Proyecto experimental para investigar un port por recompilaci?n est?tica de Manhunt PC a Android ARM64. **El juego no arranca y no hay APK.** La copia del juego permanece local y no se distribuye. Ver [estado](docs/STATUS.md) y [seguridad](docs/WORK_SAFE_POLICY.md).

Inventario est?tico (requiere Python y `pefile`): `python tools/pe_inventory.py "Manhunt Collection/Manhunt"`. No ejecuta los archivos examinados. Pruebas del supervisor: `python tests/test_worksafe.py`.
