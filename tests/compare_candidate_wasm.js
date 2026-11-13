"use strict";
const fs = require("fs");
const path = require("path");
const base = path.join(__dirname, "..", "private", "analysis", "candidate_deterministic");
const ref = JSON.parse(fs.readFileSync(path.join(base, "x86_reference.json"), "utf8"));
const report = JSON.parse(fs.readFileSync(path.join(base, "report.json"), "utf8"));
if (ref.input_sha256 !== report.input_sha256 || ref.candidate_address !== report.address ||
    ref.candidate_source_sha256 !== report.source_sha256) throw Error("Reference does not match candidate");
WebAssembly.instantiate(fs.readFileSync(path.join(base, "difftest.wasm"))).then(({instance}) => {
    const e = instance.exports;
    const regs = ["eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp"];
    for (const [index, c] of ref.cases.entries()) {
        e.run_case(c.key, c.start, c.end, c.mode, c.skew);
        if (e.get_result(c.skew) !== c.result) throw Error(`case ${index}: result differs`);
        for (const [i, name] of regs.entries()) {
            if ((e.get_reg(i) >>> 0) !== c.registers[name]) throw Error(`case ${index}: ${name} differs`);
        }
        const memory = new Uint8Array(e.memory.buffer, e.get_guest_memory() + 0x107ff0 + c.skew, 36);
        if (Buffer.from(memory).toString("hex") !== c.stack_hex) throw Error(`case ${index}: stack differs`);
        for (const [address, expected] of [[0x200000, c.object_hex], [0x210000, c.array_hex]]) {
            const bytes = new Uint8Array(e.memory.buffer, e.get_guest_memory() + address + c.skew, expected.length / 2);
            if (Buffer.from(bytes).toString("hex") !== expected) throw Error(`case ${index}: memory at ${address.toString(16)} differs`);
        }
        const mask = 0x8d5; // CF, PF, AF, ZF, SF, OF; other flags are outside this harness.
        if ((e.get_flags() & mask) !== (c.registers.eflags & mask)) throw Error(`case ${index}: arithmetic flags differ (C=${e.get_flags().toString(16)}, x86=${c.registers.eflags.toString(16)})`);
    }
    console.log(`${ref.cases.length} cases agree on output, general registers, observed memory and arithmetic flags`);
}).catch(error => { console.error(error); process.exitCode = 1; });
