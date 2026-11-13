"use strict";
const fs = require("fs");
const path = require("path");
const binary = path.join(__dirname, "..", "build", "wasm-test", "guest_memory.wasm");
WebAssembly.instantiate(fs.readFileSync(binary)).then(({instance}) => {
    const line = instance.exports.mh_memory_tests();
    if (line !== 0) {
        console.error(`guest memory test failed at tests/test_guest_memory.c:${line}`);
        process.exitCode = 1;
    } else {
        console.log("guest memory tests passed (WebAssembly, test-only memmove)");
    }
}).catch(error => { console.error(error); process.exitCode = 1; });
