"""Verify architecture and record hashes of synthetic Android test binaries."""
import hashlib,json,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    base=ROOT/'build/device-tests';items=[]
    for name in ('guest_memory_test','pe32_test'):
        path=base/name;data=path.read_bytes()
        if data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',data,16)[0]!=3 or struct.unpack_from('<H',data,18)[0]!=183:
            raise SystemExit(name+': expected AArch64 ELF PIE')
        if b'/system/bin/linker64\0' not in data:raise SystemExit(name+': Android linker not found')
        items.append({'name':name,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)})
    (base/'manifest.json').write_text(json.dumps({'abi':'arm64-v8a','tests':items},indent=2)+'\n',encoding='utf-8')
    print('Two synthetic Android ARM64 PIE tests verified; not yet run on device')
if __name__=='__main__':main()
