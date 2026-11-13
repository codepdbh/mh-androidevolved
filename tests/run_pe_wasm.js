"use strict";
const fs=require("fs"), path=require("path");
const file=path.join(__dirname,"..","build","wasm-test","pe_image.wasm");
WebAssembly.instantiate(fs.readFileSync(file)).then(({instance})=>{
    const line=instance.exports.mh_pe_tests();
    if(line){console.error(`PE test failed at tests/test_pe_image.c:${line}`);process.exitCode=1;}
    else console.log("synthetic PE32 mapping tests passed (WebAssembly)");
}).catch(error=>{console.error(error);process.exitCode=1;});
