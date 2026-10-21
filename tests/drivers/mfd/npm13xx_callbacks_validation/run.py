# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Run the same emulator assertions against either callback implementation."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--zephyr', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--implementation', choices=('candidate', 'baseline'), default='candidate')
    parser.add_argument('--compiler', choices=('gnu', 'llvm'), default='gnu')
    parser.add_argument('--sanitize', action='store_true')
    args = parser.parse_args()
    tree = args.zephyr.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parent
    app = output / 'app'
    shutil.copytree(source, app, ignore=shutil.ignore_patterns('__pycache__'))
    if args.implementation == 'baseline':
        for path in (app / 'src').iterdir():
            text = path.read_text()
            path.write_text(
                text.replace('mfd_npm13xx_event_callback', 'gpio_callback')
                .replace('npm13xx_event_t', 'uint32_t')
                .replace('event_mask', 'pin_mask')
            )
    revision = subprocess.check_output(
        ['git', '-C', str(tree), 'rev-parse', 'HEAD'], text=True
    ).strip()
    tracked = ['drivers/mfd/mfd_npm13xx.c', 'include/zephyr/drivers/mfd/npm13xx.h']
    assert not subprocess.check_output(['git', '-C', str(tree), 'diff', 'HEAD', '--', *tracked])
    environment = os.environ.copy()
    environment['ZEPHYR_BASE'] = str(tree)
    environment['ZEPHYR_TOOLCHAIN_VARIANT'] = 'host/' + args.compiler
    environment['ASAN_OPTIONS'] = 'detect_leaks=1:halt_on_error=1'
    environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
    results = {
        'revision': revision,
        'implementation': args.implementation,
        'compiler': args.compiler,
        'sanitizers': args.sanitize,
        'source_sha256': {
            name: hashlib.sha256((tree / name).read_bytes()).hexdigest() for name in tracked
        },
        'variants': [],
    }
    for part in ('1300', '1304'):
        build = output / ('build-' + part)
        configure = [
            'cmake',
            '-G',
            'Ninja',
            '-S',
            str(app),
            '-B',
            str(build),
            '-DBOARD=native_sim/native/64',
            '-DZEPHYR_MODULES=',
            '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
        ]
        if part == '1304':
            configure.append('-DEXTRA_DTC_OVERLAY_FILE=npm1304.overlay')
        if args.sanitize:
            configure.append('-DEXTRA_CONF_FILE=sanitize.conf')
        execute = [str(build / 'zephyr/zephyr.exe')]
        if args.sanitize:
            execute = ['setarch', platform.machine(), '-R', *execute]
        stages = [
            ('configure', configure),
            ('build', ['cmake', '--build', str(build), '--parallel', '4']),
            ('run', execute),
        ]
        variant = {'part': part, 'stages': []}
        results['variants'].append(variant)
        for stage, command in stages:
            log = output / (part + '-' + stage + '.log')
            with log.open('w') as stream:
                stream.write('COMMAND: ' + repr(command) + '\n')
                stream.flush()
                process = subprocess.run(
                    command,
                    cwd=tree,
                    env=environment,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=300,
                )
            variant['stages'].append({'name': stage, 'exit': process.returncode, 'log': log.name})
            (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
            if process.returncode != 0:
                raise RuntimeError(f'{part} {stage} failed; see {log}')
        text = log.read_text()
        repeats = 10 if args.sanitize else 1
        assert text.count('PASS - test_') == 17 * repeats, text
        assert 'FAIL - test_' not in text and 'SKIP - test_' not in text
        assert 'PROJECT EXECUTION SUCCESSFUL' in text
        assert text.count('EXHAUSTIVE masks=16383 clears=114688 callbacks=229376') == repeats
        config = (build / 'zephyr/.config').read_text()
        assert 'CONFIG_MFD_NPM13XX=y' in config and 'CONFIG_CPP=y' in config
        commands = json.loads((build / 'compile_commands.json').read_text())
        driver = [x for x in commands if x['file'].endswith('/drivers/mfd/mfd_npm13xx.c')]
        assert len(driver) == 1
        assert any(x['file'].endswith('/src/header.cpp') for x in commands)
        if args.sanitize:
            assert 'CONFIG_ASAN=y' in config and 'CONFIG_UBSAN=y' in config
            assert '-fsanitize=address' in driver[0]['command']
            assert '-fsanitize=undefined' in driver[0]['command']
            assert 'ERROR: AddressSanitizer' not in text and 'runtime error:' not in text
            assert 'LeakSanitizer' not in text
        variant['test_invocations'] = 17 * repeats
        variant['exhaustive_repeats'] = repeats
        (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
