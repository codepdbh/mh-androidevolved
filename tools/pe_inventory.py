"""Read-only PE metadata inventory; requires pefile. Never executes inspected files."""
import argparse, hashlib, json
from pathlib import Path
import pefile

def inspect(path, root):
 data=path.read_bytes(); pe=pefile.PE(data=data, fast_load=False)
 imports=[]
 for entry in getattr(pe,'DIRECTORY_ENTRY_IMPORT',[]):
  imports.append({'dll':entry.dll.decode('ascii','replace'),'symbols':[x.name.decode('ascii','replace') if x.name else '#'+str(x.ordinal) for x in entry.imports]})
 exports=[x.name.decode('ascii','replace') if x.name else '#'+str(x.ordinal) for x in getattr(getattr(pe,'DIRECTORY_ENTRY_EXPORT',None),'symbols',[])]
 tls=getattr(pe,'DIRECTORY_ENTRY_TLS',None)
 callbacks=[]
 if tls and tls.struct.AddressOfCallBacks:
  address=tls.struct.AddressOfCallBacks-pe.OPTIONAL_HEADER.ImageBase
  for i in range(128):
   try:
    width = 8 if pe.OPTIONAL_HEADER.Magic == 0x20b else 4
    value = (pe.get_qword_at_rva if width == 8 else pe.get_dword_at_rva)(address+i*width)
   except Exception: break
   if not value: break
   callbacks.append(hex(value))
 versions=[]
 for info in getattr(pe,'FileInfo',[]):
  for item in info:
   for table in getattr(item,'StringTable',[]): versions.append({k.decode('utf-8','replace'):v.decode('utf-8','replace') for k,v in table.entries.items()})
 return {'path':str(path.relative_to(root)), 'size':len(data), 'sha256':hashlib.sha256(data).hexdigest(), 'machine':hex(pe.FILE_HEADER.Machine), 'image_base':hex(pe.OPTIONAL_HEADER.ImageBase), 'entry_rva':hex(pe.OPTIONAL_HEADER.AddressOfEntryPoint), 'sections':[{'name':s.Name.rstrip(b'\0').decode('ascii','replace'),'virtual_address':hex(s.VirtualAddress),'virtual_size':s.Misc_VirtualSize,'raw_size':s.SizeOfRawData,'characteristics':hex(s.Characteristics)} for s in pe.sections], 'imports':imports, 'exports':exports, 'relocation_blocks':len(getattr(pe,'DIRECTORY_ENTRY_BASERELOC',[])), 'tls_present':bool(tls), 'tls_callbacks':callbacks, 'version_strings':versions, 'warnings':pe.get_warnings(), 'limitations':['Dynamic loading, SEH behavior and packing cannot be determined from imports alone.']}

def main():
 parser=argparse.ArgumentParser(); parser.add_argument('directory',type=Path); parser.add_argument('--output',type=Path,default=Path('analysis/pe_inventory.json')); args=parser.parse_args()
 root=args.directory.resolve(); results=[]; errors=[]
 for p in sorted(root.rglob('*')):
  if p.is_file() and p.suffix.lower() in {'.exe','.dll'}:
   try: results.append(inspect(p,root))
   except (OSError,pefile.PEFormatError,ValueError) as e: errors.append({'path':str(p.relative_to(root)),'error':str(e)})
 args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps({'root_name':root.name,'modules':results,'errors':errors},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
 print(f'{len(results)} modules, {len(errors)} errors -> {args.output}')
 return bool(errors)
if __name__=='__main__': raise SystemExit(main())
