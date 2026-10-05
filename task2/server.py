"""Local browser interface for the Task 2 compiler (Python standard library only)."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
import webbrowser
from compiler import ROOT, compile_source, run_target, tac_text

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def send(self, status, body, content_type='application/json; charset=utf-8'):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path == '/':
            self.send(200,(ROOT/'ui.html').read_text(encoding='utf-8'),'text/html; charset=utf-8')
        elif self.path == '/api/examples':
            self.send(200,json.dumps({p.stem:p.read_text(encoding='utf-8') for p in sorted((ROOT/'examples').glob('*.mini'))}))
        elif self.path == '/terminal':
            self.send(200,(ROOT/'terminal.html').read_text(encoding='utf-8'),'text/html; charset=utf-8')
        else: self.send(404,json.dumps({'error':'Page not found'}))
    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length','0'))
            if length < 1 or length > 100000:
                self.send(413,json.dumps({'error':'Source request must be between 1 and 100000 bytes'})); return
            request = json.loads(self.rfile.read(length))
            if self.path == '/api/terminal':
                example = request.get('example','')
                allowed = {p.stem:p for p in (ROOT/'examples').glob('*.mini')}
                if example not in allowed: raise ValueError('Unknown example')
                command = [sys.executable,str(ROOT/'compiler.py'),str(allowed[example]),'--run','both','--summary']
                run = subprocess.run(command,capture_output=True,text=True,timeout=30)
                shown = f'python compiler.py examples/{example}.mini --run both --summary'
                transcript = '$ '+shown+'\n\n'+run.stdout+run.stderr+f'\nProcess exit code: {run.returncode}\n'
                (ROOT/'evidence').mkdir(parents=True,exist_ok=True)
                (ROOT/'evidence'/f'{example}_terminal.txt').write_text(transcript,encoding='utf-8')
                self.send(200,json.dumps({'transcript':transcript,'returncode':run.returncode})); return
            source = request.get('source','')
            if not isinstance(source,str): raise ValueError('Source must be text')
            result = compile_source(source,request.get('optimize',True))
            result['tac_text'] = tac_text(result['tac'])
            result['optimized_tac_text'] = tac_text(result['optimized_tac'])
            result['executions'] = []
            if self.path == '/api/run' and result['success']:
                for target in ('c','riscv'):
                    try: result['executions'].append(run_target(result,target))
                    except (RuntimeError,subprocess.SubprocessError) as error:
                        result['executions'].append({'target':target,'returncode':1,'stdout':'','stderr':str(error)})
            elif self.path != '/api/compile' and self.path != '/api/run':
                self.send(404,json.dumps({'error':'Action not found'})); return
            self.send(200,json.dumps(result))
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
            self.send(400,json.dumps({'error':str(error)}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    url = f'http://127.0.0.1:{args.port}'
    print(f'Task 2 compiler interface: {url}',flush=True)
    if not args.no_browser:
        threading.Timer(0.5,lambda:webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
