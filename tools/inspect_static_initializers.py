"""Classify the C++ static initialisers listed in .CRT (run before WinMain).

For every initialiser, walk its direct-call closure with the pinned PCRecomp
revision and record: functions, instructions, Windows imports called, x87 use,
non-import indirect calls (vtables/function pointers), raw-pointer helpers and
unsupported instructions. Static analysis only; nothing is executed.
Writes a public summary (addresses and counts only) to analysis/static_initializers.md
and full details to private/analysis/static_initializers.json.
"""
import hashlib,json,re,struct,sys
from collections import Counter
import pefile
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
LIMIT=400
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data);base=pe.OPTIONAL_HEADER.ImageBase
    names={imp.address:(imp.name.decode() if imp.name else f'ordinal_{imp.ordinal}') for e in pe.DIRECTORY_ENTRY_IMPORT for imp in e.imports}
    crt=[s for s in pe.sections if s.Name.rstrip(b'\0')==b'.CRT'][0];raw=crt.get_data()[:crt.Misc_VirtualSize]
    entries=[p for p in struct.unpack('<%dI'%(len(raw)//4),raw[:len(raw)//4*4]) if p]
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info);dis=Disassembler(data,info.image_base,info.sections)
    cache={}
    def facts(address):
        if address in cache:return cache[address]
        func=dis.disassemble_function(address,iat)
        if not func:cache[address]=None;return None
        src=Lifter(iat_map=iat).lift_function(func);code=re.sub(r'/\*.*?\*/','',src,flags=re.S)
        icalls=re.findall(r'RECOMP_ICALL\(([^;]*)\);',code)
        imports=set();other=0
        for target in icalls:
            m=re.fullmatch(r'MEM32\(0x([0-9A-F]+)\)',target.strip())
            if m and int(m.group(1),16) in names:imports.add(names[int(m.group(1),16)])
            else:other+=1
        cache[address]={'instructions':sum(len(b.instructions) for b in func.blocks.values()),'calls':sorted(func.calls_to),
            'imports':sorted(imports),'indirect':other+len(re.findall(r'RECOMP_JMP_INDIRECT|RECOMP_ICALL_TAIL|recomp_lookup\(',code)),
            'x87':bool(re.search(r'\bfp_\w+\(|\b_st\[',code)),'todo':'RECOMP_TODO' in src,
            'raw':sorted(set(re.findall(r'\b(ADDR|memset|memcpy|MEMSET\d*|recomp_rep_movs)\(',code)))}
        return cache[address]
    results=[]
    for root in entries:
        seen=set();pending=[root];total=0;imports=set();indirect=0;x87=False;todo=False;raw=set();missing=0
        while pending and len(seen)<LIMIT:
            a=pending.pop()
            if a in seen:continue
            seen.add(a);f=facts(a)
            if f is None:missing+=1;continue
            total+=f['instructions'];imports|=set(f['imports']);indirect+=f['indirect'];x87|=f['x87'];todo|=f['todo'];raw|=set(f['raw'])
            pending.extend(f['calls'])
        results.append({'initializer':hex(root),'functions':len(seen),'instructions':total,'truncated':len(seen)>=LIMIT,'imports':sorted(imports),
                        'indirect_calls':indirect,'x87':x87,'unsupported':todo,'raw_helpers':sorted(raw),'undecoded':missing})
    def category(r):
        if r['truncated'] or r['unsupported'] or r['undecoded']:return 'grande o con código sin soporte'
        if r['indirect_calls']:return 'llamadas indirectas (vtables/punteros)'
        if r['x87']:return 'usa x87'
        if r['imports']:return 'necesita API de Windows'
        return 'autocontenido'
    cats=Counter(category(r) for r in results);api=Counter(i for r in results for i in r['imports'])
    out=ROOT/'private/analysis';out.mkdir(parents=True,exist_ok=True)
    (out/'static_initializers.json').write_text(json.dumps({'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,'results':results},indent=2)+'\n',encoding='utf-8')
    lines=['# Inicializadores estáticos (.CRT)','',
           f'Análisis estático de los {len(results)} inicializadores de C++ que el runtime ejecuta antes de `WinMain`. Para cada uno se recorre el cierre de llamadas directas (máximo {LIMIT} funciones) con la revisión fijada de PCRecomp. No se ejecuta nada; las categorías indican qué falta para traducirlos con las reglas auditadas de `tools/recomp_lift.py`.','',
           '| Categoría | Inicializadores |','| --- | --- |']+[f'| {k} | {v} |' for k,v in cats.most_common()]+['',
           'API de Windows requeridas (número de inicializadores que las alcanzan):','']+[f'- `{k}`: {v}' for k,v in api.most_common()]+['',
           '| Inicializador | Funciones | Instrucciones | Categoría |','| --- | --- | --- | --- |']+[
           f"| `{r['initializer']}` | {r['functions']}{'+' if r['truncated'] else ''} | {r['instructions']} | {category(r)} |" for r in results]
    (ROOT/'analysis/static_initializers.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(dict(cats));print(dict(api.most_common(12)))
if __name__=='__main__':main()
