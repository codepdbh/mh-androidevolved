"""Stage missing slot/menu branches without changing the validated WinMain unit.

Static disassembly and C generation only. Does not execute the original executable or the candidate.
The output is private, unlinked and unvalidated. Existing WinMain functions (including its stops)
are declared as external dependencies; that does not make the candidate runnable.
"""
import hashlib
import json
import re
from pathlib import Path
import pefile
from inspect_entrypoint import ROOT
from recomp_lift import lift_closure

ROOTS = [0x605750, 0x605bf0, 0x607b00, 0x607d60, 0x607df0, 0x607fc0, 0x608030]


def main():
    base = ROOT / 'private/analysis/winmain'
    report = json.loads((base / 'winmain_report.json').read_text(encoding='utf-8'))
    unit_hash = hashlib.sha256((base / 'winmain_unit.c').read_bytes()).hexdigest()
    if unit_hash != report['unit_sha256']:
        raise SystemExit('current WinMain unit changed since lift')
    translated = {int(item['address'], 16) for item in report['items']}
    stops = {int(a, 16) for a in report['unresolved']}
    provided = {int(a, 16) for a in report['provided']}
    if not set(ROOTS) <= stops:
        raise SystemExit('candidate roots are no longer stops; review the current unit first')
    pe = pefile.PE(str(ROOT / 'Manhunt Collection/Manhunt/manhunt.exe'))
    imports = {imp.address for entry in pe.DIRECTORY_ENTRY_IMPORT for imp in entry.imports}
    external = (translated | stops | provided) - set(ROOTS)
    candidate = lift_closure(ROOTS, external, imports, 'save_load_candidates', max_functions=64,
                             indirect=True, x87=True, provided=external, dispatch_slots={0x850000})
    api_names = set(re.findall(r'\{\s*"([^"]+)"\s*,\s*\d+\s*,', (ROOT / 'runtime/port_api.c').read_text(encoding='utf-8')))
    details = {
        'status': 'staged only; not linked, executed, or compared with x86',
        'base_unit_sha256': unit_hash,
        'roots': [hex(a) for a in ROOTS],
        'functions': len(candidate['items']),
        'instructions': sum(item['instructions'] for item in candidate['items']),
        'imports_missing_from_port': sorted(set(candidate['imports'].values()) - api_names),
        'external_current_stops': sorted({site['target'] for item in candidate['items'] for site in item['sites']
                                          if site.get('target') in report['unresolved'] and int(site['target'], 16) not in ROOTS}),
    }
    if hashlib.sha256((base / 'winmain_unit.c').read_bytes()).hexdigest() != unit_hash:
        raise SystemExit('current WinMain unit changed during staging')
    out = ROOT / 'private/analysis/save_load_candidates/staging.json'
    out.write_text(json.dumps(details, indent=2) + '\n', encoding='utf-8')
    (out.parent / 'compile_only.c').write_text(
        '#define RECOMP_GENERATED_CODE\n'
        '#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n'
        '#include "checked_dispatch_adapter.h"\n#include "virtual_cpu.h"\n'
        '#include "x87_semantics.h"\n#include "x86_semantics.h"\n'
        '#include "save_load_candidates_unit.c"\n', encoding='utf-8')
    print(json.dumps(details, indent=2))


if __name__ == '__main__':
    main()
