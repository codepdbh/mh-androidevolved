# Registro de importaciones: prueba sintética en S25

El 13 de noviembre de 2026 se compiló para `arm64-v8a` un ejecutable de prueba con `import_registry`, memoria invitada, cargador PE e importaciones. En el Galaxy S25 Ultra se verificó el SHA-256 `69d213f0b17576f4fd6125b89fe95e2f8299eaa9e62eff25177182e7a9d117c3`, se ejecutó la prueba y se confirmó la limpieza del directorio temporal.

Los casos cubren resolución por nombre y ordinal, comparación de mayúsculas de DLL, nombres de función sensibles a mayúsculas, duplicados, destinos inválidos, importaciones pendientes y aplicación de un plan completo a un PE sintético. La integración también pasó en WebAssembly. Los destinos son direcciones de prueba: no se resolvió ninguna API real de Windows y no se ejecutó el juego. Los registros detallados se mantienen en `logs/`.
