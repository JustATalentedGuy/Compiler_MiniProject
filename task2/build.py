"""Regenerate the genuine Flex/Bison frontend and compile it with GCC."""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent

def build():
    tools = ROOT / 'tools' / 'winflexbison'
    def resolve(name, windows_name):
        local = tools / windows_name
        found = str(local) if os.name == 'nt' and local.exists() else shutil.which(name)
        if not found:
            raise RuntimeError(f'{name} is required to rebuild the frontend')
        return found
    gcc = shutil.which('gcc')
    if not gcc:
        raise RuntimeError('GCC is required to build and execute the C target')
    folder = ROOT / 'frontend'
    subprocess.run([resolve('bison', 'win_bison.exe'), '-Wall', '-Werror=conflicts-sr',
                    '-Werror=conflicts-rr', '-d', '-o', 'parser.tab.c', 'parser.y'], cwd=folder, check=True)
    subprocess.run([resolve('flex', 'win_flex.exe'), '-o', 'lex.yy.c', 'scanner.l'], cwd=folder, check=True)
    binary = folder / ('frontend.exe' if os.name == 'nt' else 'frontend')
    subprocess.run([gcc, '-std=c11', '-O2', '-Wall', '-Wextra', '-o', str(binary),
                    'parser.tab.c', 'lex.yy.c', 'ast.c'], cwd=folder, check=True)
    return binary

if __name__ == '__main__':
    print('Flex and Bison frontend built:', build())
