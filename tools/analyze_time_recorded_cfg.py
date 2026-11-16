"""Walk recorded static windows only; calls remain opaque and are never run."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXPECTED='5001b64f77690316330575fcfe6acd5c5115c5476c183ffec0d86779b0686b52'
TARGETS={0x401030,0x401b00,0x493230,0x4932f0,0x4f2400,0x4f2520,0x4f2a40,0x605750,0x6059a0,0x605e40,0x60fea0,0x60feb0,0x60fec0,0x60ff60}
def main():
    folder=ROOT/'private/analysis/candidate_time';data=json.loads((folder/'unresolved_windows.json').read_text())
    if data['input_sha256']!=EXPECTED or {int(r['address'],16) for r in data['reports']}!=TARGETS:raise SystemExit('unexpected recorded windows')
    reports=[]
    for window in data['reports']:
        start=int(window['address'],16);instructions=window['instructions']
        if not 1<=len(instructions)<=256:raise SystemExit('window budget exceeded')
        by_address={int(i['address'],16):i for i in instructions}
        if len(by_address)!=len(instructions):raise SystemExit('duplicate instruction')
        visited=set();pending=[start];calls=set();indirect=[];returns=[];outside=set();unsupported=[]
        while pending:
            address=pending.pop()
            if address in visited:continue
            item=by_address.get(address)
            if item is None:outside.add(address);continue
            if not 1<=item['size']<=15:raise SystemExit('invalid instruction size')
            visited.add(address);mn=item['mnemonic'];operand=item['operands'];next_address=address+item['size']
            if mn.startswith('ret'):returns.append(address);continue
            if mn=='call':
                if operand.startswith('0x'):calls.add(int(operand,16))
                else:indirect.append(address)
            elif mn=='jmp' or mn.startswith('j') or mn.startswith('loop'):
                if operand.startswith('0x'):pending.append(int(operand,16))
                else:unsupported.append(address)
                if mn=='jmp':continue
            elif mn in ('int','int3','ud2','hlt','iret','iretd'):
                unsupported.append(address);continue
            pending.append(next_address)
        report={'address':hex(start),'reachable_in_recorded_window':len(visited),
                'return_sites':[hex(x) for x in sorted(returns)],'direct_calls':[hex(x) for x in sorted(calls)],
                'indirect_call_sites':[hex(x) for x in sorted(indirect)],'outside_window_edges':[hex(x) for x in sorted(outside)],
                'unsupported_control_flow':[hex(x) for x in sorted(unsupported)],
                'limitations':['based only on recorded linear decode','not proof of function entry or reachability from game','calls not followed']}
        reports.append(report)
        print(hex(start),'instructions:',len(visited),'direct callees:',len(calls),'unresolved edges:',len(outside)+len(unsupported))
    (folder/'unresolved_recorded_cfg.json').write_text(json.dumps({'input_sha256':EXPECTED,'reports':reports},indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
