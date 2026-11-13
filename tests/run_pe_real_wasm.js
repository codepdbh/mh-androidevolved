"use strict";
const fs=require("fs"),path=require("path"),crypto=require("crypto");
const root=path.join(__dirname,".."), wasm=path.join(root,"build","wasm-test","pe_real.wasm");
const game=path.join(root,"Manhunt Collection","Manhunt","manhunt.exe");
const expected="5001b64f77690316330575fcfe6acd5c5115c5476c183ffec0d86779b0686b52";
const digest=buffer=>crypto.createHash("sha256").update(buffer).digest("hex");
WebAssembly.instantiate(fs.readFileSync(wasm)).then(({instance})=>{
    const e=instance.exports,input=fs.readFileSync(game);
    if(digest(input)!==expected || input.length>e.pe_capacity())throw Error("unexpected input hash or size");
    const source=new Uint8Array(e.memory.buffer,e.pe_source(),input.length);source.set(input);
    if(e.pe_map(input.length)!==1)throw Error("PE loader rejected the local executable");
    const pe=input.readUInt32LE(0x3c),opt=pe+24,sections=input.readUInt16LE(pe+6),table=opt+input.readUInt16LE(pe+20);
    const size=input.readUInt32LE(opt+56),headers=input.readUInt32LE(opt+60);
    if(e.pe_size()!==size || e.pe_entry()!==input.readUInt32LE(opt+16))throw Error("metadata mismatch");
    const reference=Buffer.alloc(size);input.copy(reference,0,0,headers);
    for(let i=0;i<sections;i++){
        const s=table+i*40,rva=input.readUInt32LE(s+12),raw=input.readUInt32LE(s+16),off=input.readUInt32LE(s+20);
        if(raw)input.copy(reference,rva,off,off+raw);
    }
    const mapped=Buffer.from(e.memory.buffer,e.pe_image(),size);
    if(!reference.equals(mapped))throw Error("mapped image differs from independent section copy");
    const cstring=off=>{
        if(off>=reference.length)throw Error("reference string outside image");
        const end=reference.indexOf(0,off);if(end<0)throw Error("unterminated reference string");
        return reference.toString("ascii",off,end);
    };
    const importRva=input.readUInt32LE(opt+104),importSize=input.readUInt32LE(opt+108),imageBase=input.readUInt32LE(opt+28);
    const expectedImports=[];
    for(let p=importRva;p+20<=importRva+importSize;p+=20){
        const original=reference.readUInt32LE(p),dll=reference.readUInt32LE(p+12),iat=reference.readUInt32LE(p+16);
        if(!original&&!reference.readUInt32LE(p+4)&&!reference.readUInt32LE(p+8)&&!dll&&!iat)break;
        for(let i=0;;i++){
            const value=reference.readUInt32LE((original||iat)+i*4);if(!value)break;
            const byOrdinal=(value>>>31)!==0;
            expectedImports.push({dll:cstring(dll),name:byOrdinal?null:cstring(value+2),ordinal:byOrdinal?(value&65535):0,byOrdinal,iat:(imageBase+iat+i*4)>>>0});
        }
    }
    if(e.pe_collect_imports()!==expectedImports.length)throw Error("import count mismatch");
    expectedImports.forEach((item,i)=>{
        if(cstring(e.pe_import(i,0))!==item.dll || (item.byOrdinal?null:cstring(e.pe_import(i,1)))!==item.name ||
           Boolean(e.pe_import(i,2))!==item.byOrdinal || e.pe_import(i,3)!==item.ordinal || e.pe_import(i,4)!==item.iat)
            throw Error(`import ${i} differs`);
    });
    if(e.pe_plan_missing()!==expectedImports.length)throw Error("unresolved import plan mismatch");
    if(!reference.equals(mapped))throw Error("unresolved import plan changed the mapped image");
    if(digest(Buffer.from(source))!==expected || digest(fs.readFileSync(game))!==expected)throw Error("input changed");
    console.log(`Local PE mapped read-only: ${sections} sections, ${expectedImports.length} imports pending, ${size} bytes, entry RVA 0x${e.pe_entry().toString(16)}`);
}).catch(error=>{console.error(error);process.exitCode=1;});
