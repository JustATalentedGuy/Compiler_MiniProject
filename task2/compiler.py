"""Mini-language compiler: Flex/Bison -> semantic AST -> TAC -> C and RV32IM."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
ARITHMETIC = {'+', '-', '*', '/', '%'}
COMPARISONS = {'<', '<=', '>', '>=', '==', '!='}

def i32(value: int) -> int:
    return (value + 2**31) % 2**32 - 2**31

def calculate(op: str, a: int, b: int = 0) -> int:
    if op == 'neg': return i32(-a)
    if op == '+': return i32(a + b)
    if op == '-': return i32(a - b)
    if op == '*': return i32(a * b)
    if op in {'/', '%'}:
        if b == 0: raise ZeroDivisionError('division by zero')
        q = abs(a) // abs(b) * (-1 if (a < 0) != (b < 0) else 1)
        return i32(q if op == '/' else a - q * b)
    return int({'<': a < b, '<=': a <= b, '>': a > b, '>=': a >= b,
                '==': a == b, '!=': a != b}[op])

class SemanticAnalyzer:
    def __init__(self):
        self.scopes: list[dict] = []
        self.symbols: list[dict] = []
        self.diagnostics: list[dict] = []
        self.scope_counter = 0
        self.scope_ids: list[int] = []

    def error(self, n, message):
        self.diagnostics.append({'phase': 'semantic', 'message': message,
                                 'line': n['line'], 'column': n['column']})

    def lookup(self, n, name):
        for scope in reversed(self.scopes):
            if name in scope: return scope[name]
        self.error(n, f"Undeclared variable '{name}'")
        return None

    def expression(self, n, initialized):
        k, children = n['kind'], n['children']
        if k == 'number':
            # Compare strings first so arbitrarily long invalid literals are safe.
            digits = n['value'].lstrip('0') or '0'
            if len(digits) > 10 or (len(digits) == 10 and digits > '2147483647'):
                self.error(n, 'Integer literal exceeds the signed 32 bit range')
            n['type'] = 'int'
        elif k == 'name':
            symbol = self.lookup(n, n['value'])
            if symbol:
                n['binding'] = symbol['binding']
                if symbol['binding'] not in initialized:
                    self.error(n, f"Variable '{n['value']}' may be used before initialization")
            n['type'] = 'int'
        elif k == 'unary':
            if self.expression(children[0], initialized) != 'int':
                self.error(n, 'Unary minus requires an integer')
            n['type'] = 'int'
        else:
            types = [self.expression(c, initialized) for c in children]
            if n['value'] in ARITHMETIC:
                if types != ['int', 'int']: self.error(n, 'Arithmetic requires integer operands')
                n['type'] = 'int'
            else:
                if types[0] != types[1] or (n['value'] not in {'==', '!='} and types[0] != 'int'):
                    self.error(n, 'Comparison operands have incompatible types')
                n['type'] = 'bool'
        return n['type']

    def block(self, n, incoming):
        scope_id = self.scope_counter
        self.scope_counter += 1
        self.scope_ids.append(scope_id)
        self.scopes.append({})
        initialized = set(incoming)
        for stmt in n['children']:
            k, c = stmt['kind'], stmt['children']
            if k == 'decl':
                name = stmt['value']
                if name in self.scopes[-1]:
                    self.error(stmt, f"Duplicate declaration of '{name}' in the same scope")
                    if c: self.expression(c[0], initialized)
                    continue
                symbol = {'name': name, 'binding': f'v{len(self.symbols)}', 'type': 'int',
                          'scope': scope_id, 'depth': len(self.scopes)-1,
                          'line': stmt['line'], 'column': stmt['column']}
                self.scopes[-1][name] = symbol
                self.symbols.append(symbol)
                stmt['binding'] = symbol['binding']
                if c:
                    if self.expression(c[0], initialized) != 'int':
                        self.error(stmt, 'An int declaration requires an integer initializer')
                    initialized.add(symbol['binding'])
            elif k == 'assign':
                symbol = self.lookup(stmt, stmt['value'])
                if self.expression(c[0], initialized) != 'int':
                    self.error(stmt, 'An int variable cannot receive a boolean expression')
                if symbol:
                    stmt['binding'] = symbol['binding']
                    initialized.add(symbol['binding'])
            elif k == 'print':
                self.expression(c[0], initialized)
            elif k == 'block':
                initialized = self.block(stmt, initialized)
            elif k in {'if', 'while'}:
                if self.expression(c[0], initialized) != 'bool':
                    self.error(stmt, 'A condition must be a boolean comparison')
                first = self.block(c[1], initialized)
                if k == 'if':
                    second = self.block(c[2], initialized) if len(c) == 3 else initialized
                    initialized = first & second
                # A loop can execute zero times; its assignments are not definite afterwards.
        local_bindings = {s['binding'] for s in self.scopes.pop().values()}
        self.scope_ids.pop()
        return initialized - local_bindings

@dataclass
class Instruction:
    op: str
    dest: str | None = None
    a: str | int | None = None
    b: str | int | None = None

    def __str__(self):
        if self.op == 'label': return f'{self.dest}:'
        if self.op == 'jump': return f'goto {self.dest}'
        if self.op == 'jz': return f'ifFalse {self.a} goto {self.dest}'
        if self.op == 'print': return f'print {self.a}'
        if self.op == 'copy': return f'{self.dest} = {self.a}'
        if self.op == 'neg': return f'{self.dest} = -{self.a}'
        return f'{self.dest} = {self.a} {self.op} {self.b}'

class Lowering:
    def __init__(self): self.code, self.temps, self.labels = [], 0, 0
    def emit(self, op, dest=None, a=None, b=None): self.code.append(Instruction(op,dest,a,b))
    def label(self):
        result = f'L{self.labels}'; self.labels += 1; return result
    def expression(self, n):
        if n['kind'] == 'number': return int(n['value'])
        if n['kind'] == 'name': return n['binding']
        a = self.expression(n['children'][0])
        b = self.expression(n['children'][1]) if len(n['children']) == 2 else None
        temp = f't{self.temps}'; self.temps += 1
        self.emit('neg' if n['kind'] == 'unary' else n['value'],temp,a,b)
        return temp
    def block(self, n):
        for s in n['children']:
            k, c = s['kind'], s['children']
            if k in {'decl','assign'}:
                if c: self.emit('copy',s['binding'],self.expression(c[0]))
            elif k == 'print': self.emit('print',a=self.expression(c[0]))
            elif k == 'block': self.block(s)
            elif k == 'if':
                otherwise, end = self.label(), self.label()
                self.emit('jz',otherwise,self.expression(c[0]))
                self.block(c[1]); self.emit('jump',end); self.emit('label',otherwise)
                if len(c) == 3: self.block(c[2])
                self.emit('label',end)
            elif k == 'while':
                head, end = self.label(), self.label()
                self.emit('label',head); self.emit('jz',end,self.expression(c[0]))
                self.block(c[1]); self.emit('jump',head); self.emit('label',end)

def optimize(code):
    """Local constant propagation/folding and algebraic simplification, then temp DCE.

    Facts are deliberately discarded at every control-flow boundary. Division
    and remainder remain observable because they may raise a runtime error.
    """
    facts, result, changes = {}, [], []
    for old in code:
        if old.op == 'label': facts.clear()
        new = replace(old)
        for field in ('a','b'):
            value = getattr(new,field)
            if isinstance(value,str) and value in facts: setattr(new,field,facts[value])
        if new.op in ARITHMETIC | COMPARISONS | {'neg'}:
            if isinstance(new.a,int) and (new.op == 'neg' or isinstance(new.b,int)):
                try: new = Instruction('copy',new.dest,calculate(new.op,new.a,new.b or 0))
                except ZeroDivisionError: pass
            elif (new.op in {'+','-'} and new.b == 0) or (new.op in {'*','/'} and new.b == 1):
                new = Instruction('copy',new.dest,new.a)
            elif new.op == '+' and new.a == 0:
                new = Instruction('copy',new.dest,new.b)
            elif new.op == '*' and new.a == 1:
                new = Instruction('copy',new.dest,new.b)
            elif new.op == '*' and (new.a == 0 or new.b == 0):
                new = Instruction('copy',new.dest,0)
        if new.dest and new.op not in {'label','jump','jz'}:
            facts.pop(new.dest,None)
            if new.op == 'copy' and isinstance(new.a,int): facts[new.dest] = new.a
        if str(old) != str(new): changes.append(f'{old}  ->  {new}')
        result.append(new)
        if new.op in {'jump','jz'}: facts.clear()
    # Temps are single-assignment. Remove only side-effect-free unused defs.
    while True:
        used = {v for ins in result for v in (ins.a,ins.b) if isinstance(v,str)}
        dead = [ins for ins in result if ins.dest and ins.dest.startswith('t')
                and ins.dest not in used and ins.op not in {'/','%'}]
        if not dead: break
        for ins in dead: changes.append(f'Removed unused temporary: {ins}')
        result = [ins for ins in result if ins not in dead]
    return result, changes

def storage(code):
    return sorted({v for ins in code for v in (ins.dest,ins.a,ins.b)
                   if isinstance(v,str) and v.startswith(('v','t'))})

C_RUNTIME = '''#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
/* All arithmetic follows signed RV32 wraparound semantics. */
static int32_t wrap(uint32_t x) {
    return x <= INT32_MAX ? (int32_t)x : -1 - (int32_t)(UINT32_MAX-x);
}
static int32_t add32(int32_t a,int32_t b) { return wrap((uint32_t)a+(uint32_t)b); }
static int32_t sub32(int32_t a,int32_t b) { return wrap((uint32_t)a-(uint32_t)b); }
static int32_t mul32(int32_t a,int32_t b) { return wrap((uint32_t)a*(uint32_t)b); }
static int32_t div32(int32_t a,int32_t b) {
    if (!b) { fputs("Runtime error: division by zero\\n",stderr); exit(2); }
    if (a==INT32_MIN && b==-1) return INT32_MIN;
    return a/b;
}
static int32_t rem32(int32_t a,int32_t b) {
    if (!b) { fputs("Runtime error: division by zero\\n",stderr); exit(2); }
    if (a==INT32_MIN && b==-1) return 0;
    return a%b;
}
'''

def emit_c(code):
    rows = [C_RUNTIME,'int main(void) {']
    names = storage(code)
    if names: rows.append('    int32_t ' + ', '.join(f'{v}=0' for v in names) + ';')
    helpers = {'+':'add32','-':'sub32','*':'mul32','/':'div32','%':'rem32'}
    def value(v): return 'INT32_MIN' if v == -2**31 else str(v)
    for ins in code:
        a,b = value(ins.a),value(ins.b)
        if ins.op == 'label': rows.append(f'{ins.dest}: ;')
        elif ins.op == 'jump': rows.append(f'    goto {ins.dest};')
        elif ins.op == 'jz': rows.append(f'    if (!({a})) goto {ins.dest};')
        elif ins.op == 'print': rows.append(f'    printf("%" PRId32 "\\n", (int32_t)({a}));')
        elif ins.op == 'copy': rows.append(f'    {ins.dest} = {a};')
        elif ins.op == 'neg': rows.append(f'    {ins.dest} = sub32(0, {a});')
        elif ins.op in helpers: rows.append(f'    {ins.dest} = {helpers[ins.op]}({a}, {b});')
        else: rows.append(f'    {ins.dest} = ({a} {ins.op} {b});')
    return '\n'.join(rows + ['    return 0;','}',''])

def emit_riscv(code):
    rows = ['# RV32IM target with the RARS environment-call ABI', '.data','.align 2']
    # Prefix memory labels to avoid collisions with architectural t0-t6 registers.
    rows += [f'slot_{v}: .word 0' for v in storage(code)]
    rows += ['runtime_message: .asciz "Runtime error: division by zero\\n"',
             '.text','.globl main','main:']
    def load(reg,v):
        if isinstance(v,int): rows.append(f'    li {reg}, {v}')
        else: rows.extend([f'    la t6, slot_{v}',f'    lw {reg}, 0(t6)'])
    for ins in code:
        if ins.op == 'label': rows.append(f'{ins.dest}:'); continue
        if ins.op == 'jump': rows.append(f'    j {ins.dest}'); continue
        load('t0',ins.a)
        if ins.op == 'jz': rows.append(f'    beqz t0, {ins.dest}'); continue
        if ins.op == 'print':
            rows += ['    mv a0, t0','    li a7, 1','    ecall',
                     '    li a0, 10','    li a7, 11','    ecall']
            continue
        if ins.op == 'copy': rows.append('    mv t2, t0')
        elif ins.op == 'neg': rows.append('    neg t2, t0')
        else:
            load('t1',ins.b)
            if ins.op in {'/','%'}: rows.append('    beqz t1, runtime_error')
            simple = {'+':'add','-':'sub','*':'mul','/':'div','%':'rem','<':'slt'}
            if ins.op in simple: rows.append(f'    {simple[ins.op]} t2, t0, t1')
            elif ins.op == '>': rows.append('    slt t2, t1, t0')
            elif ins.op == '<=': rows += ['    slt t2, t1, t0','    xori t2, t2, 1']
            elif ins.op == '>=': rows += ['    slt t2, t0, t1','    xori t2, t2, 1']
            else:
                rows += ['    xor t2, t0, t1', '    seqz t2, t2' if ins.op == '==' else '    snez t2, t2']
        rows += [f'    la t6, slot_{ins.dest}','    sw t2, 0(t6)']
    rows += ['    li a0, 0','    li a7, 93','    ecall','runtime_error:',
             '    la a0, runtime_message','    li a7, 4','    ecall',
             '    li a0, 2','    li a7, 93','    ecall','']
    return '\n'.join(rows)

def compile_source(source: str, use_optimization=True):
    binary = ROOT/'frontend'/('frontend.exe' if os.name == 'nt' else 'frontend')
    if not binary.exists():
        from build import build
        binary = build()
    run = subprocess.run([str(binary)],input=source.encode('utf-8'),capture_output=True,timeout=10)
    if run.returncode not in (0,1): raise RuntimeError(run.stderr.decode(errors='replace'))
    result = json.loads(run.stdout)
    result.update({'success': False, 'symbols': [], 'tac': [], 'optimized_tac': [],
                   'optimizations': [], 'c': '', 'riscv': ''})
    if result['diagnostics']: return result
    sem = SemanticAnalyzer(); sem.block(result['ast'],set())
    result['symbols'], result['diagnostics'] = sem.symbols,sem.diagnostics
    if sem.diagnostics: return result
    lowering = Lowering(); lowering.block(result['ast'])
    optimized, changes = optimize(lowering.code) if use_optimization else (lowering.code,[])
    result.update({'success': True, 'tac': [asdict(i) for i in lowering.code],
                   'optimized_tac': [asdict(i) for i in optimized], 'optimizations': changes,
                   'c': emit_c(optimized), 'riscv': emit_riscv(optimized)})
    return result

def tac_text(records):
    return '\n'.join(str(Instruction(**r)) for r in records)

def run_target(result, target, timeout=10):
    if not result['success']: raise ValueError('Compilation failed; target execution is unavailable')
    with tempfile.TemporaryDirectory(prefix='mini_target_') as directory:
        folder = Path(directory)
        if target == 'c':
            gcc = shutil.which('gcc')
            if not gcc: raise RuntimeError('GCC was not found')
            source = folder/'program.c'; source.write_text(result['c'],encoding='utf-8')
            binary = folder/('program.exe' if os.name == 'nt' else 'program')
            built = subprocess.run([gcc,'-std=c11','-O0',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=timeout)
            if built.returncode: raise RuntimeError(built.stderr)
            command = [str(binary)]
        elif target == 'riscv':
            java, jar = shutil.which('java'), ROOT/'tools'/'rars.jar'
            if not java or not jar.exists(): raise RuntimeError('Java and the bundled RARS simulator are required')
            source = folder/'program.s'; source.write_text(result['riscv'],encoding='utf-8')
            command = [java,'-jar',str(jar),'nc','me','ae2','se3','1000000',str(source)]
        else: raise ValueError(f'Unknown target: {target}')
        run = subprocess.run(command,capture_output=True,text=True,timeout=timeout)
        stderr = run.stderr.replace('\r\n','\n').strip()
        # RARS normally appends an informational termination message to stderr.
        stderr = '\n'.join(line for line in stderr.splitlines() if line.strip() and
                            not line.startswith('Program terminated by calling exit'))
        if 'maximum step limit' in stderr.lower():
            raise RuntimeError('RISC-V execution exceeded the simulation step limit')
        return {'target':target,'stdout':run.stdout.replace('\r\n','\n'),
                'stderr':stderr,'returncode':run.returncode}

def save_result(result, folder):
    folder = Path(folder); folder.mkdir(parents=True,exist_ok=True)
    (folder/'compilation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (folder/'tokens.json').write_text(json.dumps(result['tokens'],indent=2),encoding='utf-8')
    if result['ast']: (folder/'ast.json').write_text(json.dumps(result['ast'],indent=2),encoding='utf-8')
    (folder/'symbols.json').write_text(json.dumps(result['symbols'],indent=2),encoding='utf-8')
    if result['success']:
        for name, content in [('tac.txt',tac_text(result['tac'])),('optimized_tac.txt',tac_text(result['optimized_tac'])),
                              ('program.c',result['c']),('program.s',result['riscv'])]:
            (folder/name).write_text(content,encoding='utf-8')
    else:
        # Avoid leaving stale generated targets after recompiling an invalid input.
        for name in ('program.c','program.s','tac.txt','optimized_tac.txt','ast.json'):
            if name == 'ast.json' and result['ast']: continue
            (folder/name).unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--run',choices=['c','riscv','both'])
    parser.add_argument('--no-opt',action='store_true')
    parser.add_argument('--summary',action='store_true',help='Show a compact terminal demonstration')
    args = parser.parse_args()
    try:
        source = args.source.read_text(encoding='utf-8-sig')
        result = compile_source(source,not args.no_opt)
        if args.out: save_result(result,args.out)
        print('SOURCE\n'+source.rstrip())
        if args.summary:
            print(f"\nLEXICAL ANALYSIS: {len(result['tokens'])} tokens")
            if not result['success']:
                for error in result['diagnostics']:
                    print(f"{error['phase'].upper()} ERROR {error['line']}:{error['column']}: {error['message']}")
                print('Target generation stopped.')
                return 1
            print('SYNTAX ANALYSIS: PASS; AST generated')
            print(f"SEMANTIC ANALYSIS: PASS; {len(result['symbols'])} symbols")
            print(f"TAC: {len(result['tac'])} -> {len(result['optimized_tac'])} instructions")
            print('TARGETS: C and RISC-V RV32IM generated')
            outputs = []
            if args.run:
                for target in ['c','riscv'] if args.run == 'both' else [args.run]:
                    output=run_target(result,target); outputs.append(output)
                    print(f"\n{target.upper()} OUTPUT (exit {output['returncode']}):")
                    print(output['stdout'],end='')
                    if output['stderr']: print(output['stderr'])
                if len(outputs)==2:
                    match=outputs[0]['stdout']==outputs[1]['stdout'] and all(r['returncode']==0 for r in outputs)
                    print('\nOUTPUT COMPARISON: '+('MATCH' if match else 'FAILED'))
                    if not match: return 1
            return next((r['returncode'] for r in outputs if r['returncode']),0)
        print('\nTOKENS')
        print(' '.join(f"{t['type']}({t['lexeme']})@{t['line']}:{t['column']}" for t in result['tokens']))
        if not result['success']:
            for error in result['diagnostics']:
                print(f"{error['phase'].upper()} ERROR {error['line']}:{error['column']}: {error['message']}")
            return 1
        print('\nSYMBOL TABLE\n'+json.dumps(result['symbols'],indent=2))
        print('\nAST\n'+json.dumps(result['ast'],indent=2))
        print('\nTAC\n'+tac_text(result['tac']))
        print('\nOPTIMIZED TAC\n'+tac_text(result['optimized_tac']))
        print('\nOPTIMIZATIONS\n'+'\n'.join(result['optimizations']))
        print('\nC TARGET\n'+result['c'])
        print('\nRISC-V TARGET\n'+result['riscv'])
        status = 0
        if args.run:
            for target in ['c','riscv'] if args.run == 'both' else [args.run]:
                output = run_target(result,target)
                print(f"\n{target.upper()} EXECUTION exit={output['returncode']}")
                print(output['stdout'],end='')
                if output['stderr']: print(output['stderr'])
                status = status or output['returncode']
        return status
    except (OSError,RuntimeError,ValueError,subprocess.SubprocessError) as error:
        print(f'COMPILER ERROR: {error}')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
