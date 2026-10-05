"""Build and launch the Task 2 compiler demo.

Run: python demo.py [--port 8765] [--no-browser]
Requires Python 3.10+, GCC and Java. On non-Windows systems install Flex and
Bison as well. Windows generator tools and the RARS simulator are bundled.
"""
from pathlib import Path
import runpy
import shutil
import sys

def main():
    project = Path(__file__).resolve().parent / 'task2'
    sys.path.insert(0, str(project))
    if '--help' not in sys.argv and '-h' not in sys.argv:
        missing = [name for name in ('gcc', 'java') if not shutil.which(name)]
        if missing:
            print('Required tools missing from PATH: ' + ', '.join(missing), file=sys.stderr)
            return 1
        from build import build
        try:
            print('Building the Lex/Flex and Yacc/Bison frontend...', flush=True)
            build()
        except (OSError, RuntimeError) as error:
            print(str(error), file=sys.stderr)
            return 1
    runpy.run_path(str(project / 'server.py'), run_name='__main__')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
