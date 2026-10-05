"""End-to-end and negative tests for Task 2; no third-party test dependency."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compiler import ROOT, compile_source, run_target, save_result

class CompilerTests(unittest.TestCase):
    def assert_outputs(self, source, expected):
        for optimized in (False,True):
            result = compile_source(source,optimized)
            self.assertTrue(result['success'],result['diagnostics'])
            for target in ('c','riscv'):
                with self.subTest(optimized=optimized,target=target):
                    execution = run_target(result,target)
                    self.assertEqual(execution['returncode'],0,execution)
                    self.assertEqual(execution['stdout'],expected)
                    self.assertEqual(execution['stderr'],'')

    def test_three_required_inputs(self):
        cases = [('01_arithmetic','28\n'),('02_factorial','120\n'),('03_branch_scope','3\n-11\n17\n')]
        records = []
        for name, expected in cases:
            source = (ROOT/'examples'/f'{name}.mini').read_text()
            self.assert_outputs(source,expected)
            result = compile_source(source)
            save_result(result,ROOT/'evidence'/name)
            outputs = [run_target(result,target) for target in ('c','riscv')]
            for execution in outputs:
                self.assertEqual(execution['returncode'],0,execution)
                self.assertEqual(execution['stdout'],expected)
            record = {'input':name,'expected':expected,'executions':outputs,
                      'tokens':len(result['tokens']),'tac_before':len(result['tac']),
                      'tac_after':len(result['optimized_tac']),'passed':True}
            records.append(record)
            print(f"INPUT {name}: C = RISC-V = {expected.strip().replace(chr(10),', ')}; PASS",flush=True)
        (ROOT/'evidence'/'three_inputs.json').write_text(json.dumps(records,indent=2))

    def test_semantic_errors(self):
        cases = [
            ('print(missing);','Undeclared'),
            ('missing = 1;','Undeclared'),
            ('int x; print(x);','before initialization'),
            ('int x = x + 1;','before initialization'),
            ('int x=1; int x=2;','Duplicate'),
            ('int x=1<2;','initializer'),
            ('int x=1; x=2<3;','boolean'),
            ('if (1) { print(1); }','condition'),
            ('print((1<2)+1);','Arithmetic'),
            ('int x; if (1<2) { x=1; } print(x);','before initialization'),
            ('int x; while (1<2) { x=1; } print(x);','before initialization'),
            ('{ int x=1; } print(x);','Undeclared'),
            ('int x=2147483648;','range'),
            ('int x='+('9'*5000)+';','range'),
            ('print(1 < (2<3));','incompatible'),
        ]
        for source, expected in cases:
            with self.subTest(source=source[:80]):
                result = compile_source(source)
                self.assertFalse(result['success'])
                self.assertTrue(any(expected.lower() in e['message'].lower() for e in result['diagnostics']),result)
                self.assertFalse(result['c']); self.assertFalse(result['riscv'])

    def test_lexical_and_syntax_errors(self):
        cases = [('int x=@;','lexical'),('/* unfinished','lexical'),
                 ('int x=1 print(x);','syntax'),('while (1<2) {','syntax'),
                 ('if (1<2) print(1);','syntax')]
        for source,phase in cases:
            with self.subTest(source=source):
                result=compile_source(source)
                self.assertFalse(result['success'])
                self.assertTrue(any(e['phase']==phase for e in result['diagnostics']))
                self.assertFalse(result['tac'])

    def test_token_locations_and_comments(self):
        result=compile_source('// comment\nint integer = 2; /* ignored */\nprint(integer);')
        self.assertTrue(result['success'])
        self.assertEqual(result['tokens'][0],{'type':'INT','lexeme':'int','line':2,'column':1})
        self.assertEqual(result['tokens'][1]['type'],'IDENT')
        self.assertEqual(result['tokens'][1]['lexeme'],'integer')
        self.assertEqual(result['tokens'][-1]['line'],3)
        # The scanner continues to display tokens after an unrecoverable parser error.
        bad=compile_source('int x = ; print(7);')
        self.assertTrue(any(t['lexeme']=='print' for t in bad['tokens']))

    def test_integer_semantics_and_comparisons(self):
        self.assert_outputs('''int x=2147483647; x=x+1; print(x);
int y=-2147483647-1; print(y/-1); print(y%-1);
print(-7/3); print(-7%3); print(7/-3); print(7%-3);
print(1<2); print(2<=2); print(3>2); print(3>=3); print(2==2); print(2!=3);
print((1<2)==(3>2)); print(2+3*4); print((2+3)*4);''',
                            '-2147483648\n-2147483648\n0\n-2\n-1\n-2\n1\n1\n1\n1\n1\n1\n1\n1\n14\n20\n')

    def test_branch_paths_scope_and_loop(self):
        self.assert_outputs('''int x; if (2==2) { x=7; } else { x=9; }
print(x); { int x=2; print(x); } print(x);
int n=3; int sum=0;
while(n>0) { if(n%2==0) { sum=sum+n; } else { sum=sum+1; } n=n-1; }
print(sum); while(1>2) { print(99); }''','7\n2\n7\n4\n')

    def test_optimizer_preserves_errors(self):
        for source in ('print(1/0);','int x=1/0; print(x*0);','print(1%0);'):
            for optimized in (False,True):
                result=compile_source(source,optimized)
                self.assertTrue(result['success'])
                for target in ('c','riscv'):
                    execution=run_target(result,target)
                    self.assertEqual(execution['returncode'],2,execution)
                    self.assertIn('division by zero',execution['stdout']+execution['stderr'])
        # An error in a branch that is never entered must not become a compile error.
        self.assert_outputs('if(1>2) { print(1/0); } else { print(9); }','9\n')

    def test_empty_program(self): self.assert_outputs('/* no statements */','')

    def test_constant_folding_reduces_tac(self):
        result=compile_source('int x=(2+3)*4; print(x);')
        self.assertTrue(result['success'])
        self.assertLess(len(result['optimized_tac']),len(result['tac']))
        self.assertIn('print 20','\n'.join(result['optimizations']))

if __name__ == '__main__':
    unittest.main(verbosity=2)
