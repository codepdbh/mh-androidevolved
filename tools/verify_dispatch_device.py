"""Verify and hash the synthetic Android ARM64 dispatch test executable."""
import hashlib,json,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    base=ROOT/'build/device-tests';path=base/'dispatch_test';data=path.read_bytes()
    if data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',data,16)[0]!=3 or struct.unpack_from('<H',data,18)[0]!=183:
        raise SystemExit('dispatch_test: expected AArch64 ELF PIE')
    if b'/system/bin/linker64\0' not in data:raise SystemExit('dispatch_test: Android linker not found')
    item={'name':'dispatch_test','sha256':hashlib.sha256(data).hexdigest(),'size':len(data)}
    (base/'dispatch_manifest.json').write_text(json.dumps({'abi':'arm64-v8a','tests':[item]},indent=2)+'\n',encoding='utf-8')
    print('Synthetic Android ARM64 dispatch PIE verified; not yet run on device')
if __name__=='__main__':main()
