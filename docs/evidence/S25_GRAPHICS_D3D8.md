# Selector de refresco sobre el shim de Direct3D 8 — 2026-11-17

**Shim** (`runtime/d3d8.{h,c}`, código público). Los objetos COM viven en memoria del invitado: el primer dword es un puntero a una vtable del invitado, cuyas entradas son direcciones falsas (`0x1e10000 + 0x100*interfaz + 4*método`) que el despacho envía a `mh_d3d8_call()`. Los métodos siguen la convención stdcall de COM. El adaptador es una pantalla virtual con 12 modos fijos (seis tamaños, `X8R8G8B8` y `R5G6B5`, 60 Hz). De `IDirect3D8` están implementados `QueryInterface` (sin otras interfaces), `AddRef`, `Release`, `GetAdapterCount`, `GetAdapterModeCount`, `EnumAdapterModes`, `GetAdapterDisplayMode` y `CheckDeviceType`. El resto devuelve `MH_D3D8_UNIMPLEMENTED` con el nombre del método, en lugar de inventar un resultado. No hay renderizado.

**Pruebas sintéticas.** `tests/test_d3d8.c`: 23 comprobaciones (`worksafe.test_d3d8()`), sin código del juego.

**Prueba del juego.** `tools/lift_graphics_d3d8.py` traduce `0x4c0830`, que recorre los modos del adaptador y elige la frecuencia de refresco. Antes verifica que el thunk `0x64408c` es exactamente `jmp [Direct3DCreate8]`. `tests/graphics_d3d8_native.c` se compara con `tools/probe_graphics_d3d8_x86.py`: 48 casos (cuatro tamaños, tres profundidades, dos adaptadores y dos alineaciones de pila), comparando registros, número de llamadas COM, pila y heap COM. **Coinciden en Windows x64 y en el S25 `SM-S938B` (Android 17).** Binario ARM64 validado: `4f04ebe6…`.

**Fallo corregido.** `recomp_types.h` define `eax` como `g_eax`. Una variable local `eax` en el despacho COM del arnés tapaba la global, de modo que el resultado de cada método no llegaba al código traducido. El bucle de modos daba unos 30 millones de vueltas por caso. Las locales del arnés no deben llamarse como un registro x86.

**Límites.** Solo `IDirect3D8` y una función del juego. `CreateDevice`, `IDirect3DDevice8` y el renderizado sobre OpenGL ES están por hacer.
