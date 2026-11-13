"""Read the ELF dynamic symbol table; do not load or execute the library."""
import struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    if sys.argv[1:] not in ([],['--cmake']):raise SystemExit('invalid arguments')
    path=ROOT/('build/android-cmake-check/libmh_runtime.so' if sys.argv[1:] else 'build/android-native-check/libmh_runtime.so')
    data=path.read_bytes()
    if data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',data,16)[0]!=3 or struct.unpack_from('<H',data,18)[0]!=183:
        raise SystemExit('expected Android AArch64 ELF shared object')
    shoff=struct.unpack_from('<Q',data,40)[0];entry,count=struct.unpack_from('<HH',data,58)
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,shoff+i*entry) for i in range(count)]
    exported=set()
    for s in sections:
        if s[1]!=11:continue
        offset,size,link,entsize=s[4],s[5],s[6],s[9]
        if not entsize or link>=len(sections):raise SystemExit('invalid dynamic symbol table')
        strings=sections[link];names=data[strings[4]:strings[4]+strings[5]]
        for pos in range(offset,offset+size,entsize):
            name,info,other,index,value,length=struct.unpack_from('<IBBHQQ',data,pos)
            if index==0 or not name or name>=len(names):continue
            end=names.find(b'\0',name)
            if end<0:raise SystemExit('invalid symbol name')
            exported.add(names[name:end].decode('utf-8','replace'))
    names={'Java_com_manhuntae_android_MainActivity_nativeGetRuntimeDiagnostic',
           'Java_com_manhuntae_android_MainActivity_nativeInspectKnownPe'}
    if not names.issubset(exported):raise SystemExit('expected JNI exports missing: '+str(sorted(names-exported)))
    print('AArch64 ELF shared object contains both expected JNI exports')
if __name__=='__main__': main()
