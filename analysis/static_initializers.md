# Inicializadores estáticos (.CRT)

Análisis estático de los 98 inicializadores de C++ que el runtime ejecuta antes de `WinMain`. Para cada uno se recorre el cierre de llamadas directas (máximo 400 funciones) con la revisión fijada de PCRecomp. No se ejecuta nada; las categorías indican qué falta para traducirlos con las reglas auditadas de `tools/recomp_lift.py`.

| Categoría | Inicializadores |
| --- | --- |
| autocontenido | 63 |
| llamadas indirectas (vtables/punteros) | 33 |
| necesita API de Windows | 2 |

API de Windows requeridas (número de inicializadores que las alcanzan):

- `EnterCriticalSection`: 10
- `GlobalAlloc`: 10
- `LeaveCriticalSection`: 10
- `DeleteCriticalSection`: 9
- `ExitProcess`: 9
- `GlobalFree`: 9
- `MessageBoxA`: 9
- `TlsGetValue`: 9
- `TlsSetValue`: 9
- `CreateEventA`: 1
- `CreateFileA`: 1
- `GetTickCount`: 1

| Inicializador | Funciones | Instrucciones | Categoría |
| --- | --- | --- | --- |
| `0x402210` | 29 | 1491 | necesita API de Windows |
| `0x40abc0` | 4 | 90 | llamadas indirectas (vtables/punteros) |
| `0x40ade0` | 3 | 23 | autocontenido |
| `0x40af00` | 58 | 1018 | autocontenido |
| `0x417420` | 3 | 68 | llamadas indirectas (vtables/punteros) |
| `0x41c320` | 2 | 21 | autocontenido |
| `0x42d410` | 10 | 294 | llamadas indirectas (vtables/punteros) |
| `0x437520` | 132 | 13542 | llamadas indirectas (vtables/punteros) |
| `0x43d0e0` | 139 | 13806 | llamadas indirectas (vtables/punteros) |
| `0x444bc0` | 4 | 248 | autocontenido |
| `0x455ff0` | 57 | 2218 | llamadas indirectas (vtables/punteros) |
| `0x456b10` | 3 | 49 | llamadas indirectas (vtables/punteros) |
| `0x45aea0` | 3 | 262 | necesita API de Windows |
| `0x46f1b0` | 2 | 55 | autocontenido |
| `0x4726d0` | 2 | 20 | autocontenido |
| `0x476c00` | 18 | 526 | autocontenido |
| `0x479030` | 3 | 65 | llamadas indirectas (vtables/punteros) |
| `0x47ff10` | 2 | 20 | autocontenido |
| `0x4815d0` | 2 | 20 | autocontenido |
| `0x484e40` | 2 | 28 | autocontenido |
| `0x4887d0` | 2 | 48 | autocontenido |
| `0x48a000` | 4 | 95 | llamadas indirectas (vtables/punteros) |
| `0x4918a0` | 132 | 13534 | llamadas indirectas (vtables/punteros) |
| `0x491ca0` | 2 | 17 | autocontenido |
| `0x491d90` | 2 | 17 | autocontenido |
| `0x4925c0` | 3 | 77 | llamadas indirectas (vtables/punteros) |
| `0x493870` | 2 | 32 | autocontenido |
| `0x493fe0` | 2 | 44 | autocontenido |
| `0x4979b0` | 132 | 13549 | llamadas indirectas (vtables/punteros) |
| `0x499e70` | 3 | 47 | llamadas indirectas (vtables/punteros) |
| `0x49b390` | 132 | 13543 | llamadas indirectas (vtables/punteros) |
| `0x4b33c0` | 4 | 133 | llamadas indirectas (vtables/punteros) |
| `0x4bb0b0` | 3 | 23 | autocontenido |
| `0x4bb2c0` | 2 | 19 | autocontenido |
| `0x4bba80` | 3 | 37 | autocontenido |
| `0x4c3a80` | 4 | 62 | autocontenido |
| `0x4c4760` | 132 | 13534 | llamadas indirectas (vtables/punteros) |
| `0x4cb4d0` | 2 | 21 | autocontenido |
| `0x4cdd40` | 2 | 20 | autocontenido |
| `0x4d6500` | 18 | 1458 | autocontenido |
| `0x4d8700` | 4 | 37 | autocontenido |
| `0x4dcc80` | 2 | 44 | autocontenido |
| `0x4df500` | 3 | 29 | autocontenido |
| `0x4e2d30` | 3 | 29 | autocontenido |
| `0x4e4b10` | 3 | 78 | autocontenido |
| `0x4e7640` | 4 | 72 | llamadas indirectas (vtables/punteros) |
| `0x4f06d0` | 2 | 30 | autocontenido |
| `0x4f2320` | 2 | 34 | autocontenido |
| `0x4fb420` | 2 | 48 | autocontenido |
| `0x518ef0` | 2 | 23 | autocontenido |
| `0x522bc0` | 9 | 153 | llamadas indirectas (vtables/punteros) |
| `0x524bb0` | 2 | 19 | autocontenido |
| `0x525c10` | 2 | 20 | autocontenido |
| `0x525ee0` | 2 | 19 | autocontenido |
| `0x541d60` | 4 | 104 | llamadas indirectas (vtables/punteros) |
| `0x543470` | 2 | 44 | autocontenido |
| `0x54f100` | 4 | 221 | autocontenido |
| `0x555ef0` | 2 | 65 | autocontenido |
| `0x5564b0` | 2 | 36 | autocontenido |
| `0x55c210` | 42 | 1398 | llamadas indirectas (vtables/punteros) |
| `0x55f240` | 2 | 21 | autocontenido |
| `0x55fbb0` | 2 | 20 | autocontenido |
| `0x563ab0` | 2 | 30 | autocontenido |
| `0x5648a0` | 2 | 30 | autocontenido |
| `0x56f910` | 2 | 47 | autocontenido |
| `0x56fa10` | 2 | 21 | autocontenido |
| `0x578480` | 2 | 48 | autocontenido |
| `0x5832d0` | 2 | 30 | autocontenido |
| `0x587a90` | 2 | 21 | autocontenido |
| `0x589d70` | 2 | 643 | autocontenido |
| `0x5924a0` | 4 | 222 | autocontenido |
| `0x5934c0` | 6 | 207 | llamadas indirectas (vtables/punteros) |
| `0x594ae0` | 3 | 67 | llamadas indirectas (vtables/punteros) |
| `0x596140` | 3 | 60 | llamadas indirectas (vtables/punteros) |
| `0x59e1d0` | 3 | 63 | llamadas indirectas (vtables/punteros) |
| `0x5a6ea0` | 4 | 215 | llamadas indirectas (vtables/punteros) |
| `0x5af3e0` | 3 | 47 | llamadas indirectas (vtables/punteros) |
| `0x5b6d40` | 1 | 49 | autocontenido |
| `0x5bd5b0` | 41 | 219 | autocontenido |
| `0x5c1b20` | 3 | 23 | autocontenido |
| `0x5c4370` | 3 | 78 | llamadas indirectas (vtables/punteros) |
| `0x5cb2a0` | 2 | 17 | autocontenido |
| `0x5cda80` | 3 | 47 | llamadas indirectas (vtables/punteros) |
| `0x5d1c80` | 3 | 83 | llamadas indirectas (vtables/punteros) |
| `0x5d4120` | 2 | 39 | autocontenido |
| `0x5d4ee0` | 2 | 21 | autocontenido |
| `0x5e2220` | 3 | 85 | llamadas indirectas (vtables/punteros) |
| `0x5fe5e0` | 3 | 87 | llamadas indirectas (vtables/punteros) |
| `0x604f90` | 2 | 21 | autocontenido |
| `0x6086d0` | 98 | 8935 | llamadas indirectas (vtables/punteros) |
| `0x6088e0` | 2 | 20 | autocontenido |
| `0x609540` | 3 | 84 | llamadas indirectas (vtables/punteros) |
| `0x60ed60` | 3 | 31 | autocontenido |
| `0x60f550` | 2 | 20 | autocontenido |
| `0x625be0` | 1 | 7 | autocontenido |
| `0x6280c0` | 1 | 7 | autocontenido |
| `0x6546a0` | 2 | 36 | autocontenido |
| `0x666950` | 2 | 36 | autocontenido |
