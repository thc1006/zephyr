# SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

"""Require a runtime assertion failure for each deliberate driver regression."""

import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def replace_once(text, before, after):
    assert text.count(before) == 1
    return text.replace(before, after, 1)


def mutate(text, name):
    if name == 'unsafe-walk':
        text = replace_once(
            text,
            'SYS_SLIST_FOR_EACH_CONTAINER_SAFE(callbacks, cb, tmp, node)',
            'SYS_SLIST_FOR_EACH_CONTAINER(callbacks, cb, node)',
        )
        text = replace_once(text, '*cb, *tmp;', '*cb;')
        expected = 'test_self_removal_preserves_other_subscriber'
    elif name == 'clear-first':
        call = '\t\t\tfire_callbacks(&data->callbacks, data->dev, BIT(i));\n\n'
        text = replace_once(text, call, '')
        anchor = '\t\t\tif (ret < 0) {\n\t\t\t\tk_work_submit(&data->work);'
        text = replace_once(text, anchor, call + anchor)
        expected = 'test_all_event_bit_mappings'
    elif name in ('reject-reregistration', 'reject-undefined-mask'):
        anchor = '\t__ASSERT(callback->handler != NULL, "No callback handler!");\n'
        if name == 'reject-reregistration':
            condition = 'sys_slist_find(callbacks, &callback->node, NULL)'
            expected = 'test_repeated_add_moves_callback_without_duplication'
        else:
            condition = '(callback->event_mask & ~BIT_MASK(NPM13XX_EVENT_MAX)) != 0U'
            expected = 'test_undefined_mask_bits_are_accepted_and_not_reported'
        text = replace_once(
            text,
            anchor,
            anchor + '\n\tif (add && (' + condition + ')) {\n\t\treturn -EINVAL;\n\t}\n',
        )
    elif name == 'link-before-write':
        anchor = '\t/* Enable interrupts for specified events */'
        text = replace_once(
            text, anchor, '\t(void)manage_callback(&data->callbacks, callback, true);\n\n' + anchor
        )
        expected = 'test_failed_registration_does_not_link_callback'
    elif name == 'ignore-registration-error':
        start = text.index('int mfd_npm13xx_add_callback(')
        end = text.index('int mfd_npm13xx_remove_callback(', start)
        body = text[start:end]
        assert body.count('if (ret < 0)') == 2
        text = text[:start] + body.replace('if (ret < 0)', 'if (ret < 0 && false)') + text[end:]
        expected = 'test_failed_registration_does_not_link_callback'
    else:
        raise AssertionError(name)
    return text, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--zephyr', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base = args.zephyr.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = Path(__file__).resolve().parent
    revision = subprocess.check_output(
        ['git', '-C', str(base), 'rev-parse', 'HEAD'], text=True
    ).strip()

    def run(name):
        tree = output / (name + '-source')
        subprocess.run(
            ['git', '-C', str(base), 'worktree', 'add', '--detach', str(tree), revision],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        path = tree / 'drivers/mfd/mfd_npm13xx.c'
        text, expected = mutate(path.read_text(), name)
        path.write_text(text)
        (output / (name + '.patch')).write_bytes(
            subprocess.check_output(['git', '-C', str(tree), 'diff'])
        )
        build = output / (name + '-build')
        environment = os.environ.copy()
        environment['ZEPHYR_BASE'] = str(tree)
        environment['ZEPHYR_TOOLCHAIN_VARIANT'] = 'host/gnu'
        commands = [
            (
                'configure',
                [
                    'cmake',
                    '-G',
                    'Ninja',
                    '-S',
                    str(app),
                    '-B',
                    str(build),
                    '-DBOARD=native_sim/native/64',
                    '-DZEPHYR_MODULES=',
                ],
            ),
            ('build', ['cmake', '--build', str(build), '--parallel', '4']),
            ('run', [str(build / 'zephyr/zephyr.exe')]),
        ]
        result = {
            'mutation': name,
            'revision': revision,
            'part': '1300',
            'expected_failed_test': expected,
            'stages': [],
        }
        for stage, command in commands:
            log = output / (name + '-' + stage + '.log')
            with log.open('w') as stream:
                process = subprocess.run(
                    command,
                    cwd=tree,
                    env=environment,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=300,
                )
            result['stages'].append({'name': stage, 'exit': process.returncode, 'log': log.name})
            if stage != 'run':
                assert process.returncode == 0, result
            else:
                assert process.returncode != 0, result
                assert 'FAIL - ' + expected in log.read_text(), result
        return result

    names = (
        'unsafe-walk',
        'clear-first',
        'reject-reregistration',
        'reject-undefined-mask',
        'link-before-write',
        'ignore-registration-error',
    )
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(run, names))
    (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
