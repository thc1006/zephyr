.. SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
.. SPDX-License-Identifier: Apache-2.0

nPM13xx callback validation
##########################

This branch supplies review material for Zephyr PR #123060. It adds tests
to revision ``81eaec43183f86d803b4fae51ecb84afc3f3f26b``; it is not the
production PR branch. The driver, public header and sample are unchanged.
The GPIO-based baseline is main ``f70d5b0f21f076ef0a4c61a0707710f1ae3d28f2``.

The seventeen emulator tests link the real driver, kernel, system workqueue
and I2C/GPIO emulators. They check per-event delivery before clear, filtering,
self-removal, re-registration, all fourteen mappings, read retry, empty and
undefined masks, and a C++11 caller. Clear failures cover all fourteen event
positions, both before and after the emulated write takes effect. Registration
failures cover all twenty-eight clear/enable writes. The latter checks that a
failed add does not link the callback; it does not promise hardware rollback.

One test traverses all 16,383 nonempty firing masks with three fixed
subscriptions: ``0x3fff``, ``0x1555`` and ``0x2aaa``. Each traversal expects
114,688 clears and 229,376 callbacks, with their precise order and masks.
This does not enumerate every possible subscription or thread interleaving.

Run the tests
*************

Use a configured Zephyr build environment with CMake, Ninja, host GCC/G++,
32-bit host libraries and the dependencies in ``scripts/requirements-build.txt``.
The recorded environment is ``ghcr.io/zephyrproject-rtos/ci:v0.29.2``, GCC 13.3
and LLVM 20 on Linux x86_64. The native tests need no HAL modules.

Set ``app`` to this directory and ``source_tree`` to the PR checkout. Choose
new output directories; the runner refuses to overwrite an existing one.

.. code-block:: bash

   app=/absolute/path/to/validation/tests/drivers/mfd/npm13xx_callbacks_validation
   source_tree=/absolute/path/to/zephyr-pr
   uv run "$app/run.py" --zephyr "$source_tree" --output /tmp/npm13xx-gnu
   LLVM_TOOLCHAIN_PATH=/usr/lib/llvm-20 uv run "$app/run.py" \
     --zephyr "$source_tree" --compiler llvm --output /tmp/npm13xx-llvm

Each command builds and executes nPM1300 and nPM1304 on
``native_sim/native/64``: seventeen passes per variant, with no skips.
For the baseline comparison, pass ``--implementation baseline`` and point
``--zephyr`` at the stated main revision. Only the callback type, mask type
and field spelling are adapted; assertions and fault injection stay the same.

Twister also runs both variants on the default 32-bit host target:

.. code-block:: bash

   export ZEPHYR_BASE="$source_tree"
   export ZEPHYR_TOOLCHAIN_VARIANT=host/gnu
   west twister -T "$app" -p native_sim/native -x ZEPHYR_MODULES= \
     --inline-logs --outdir /tmp/npm13xx-twister-gnu

Repeat with ``host/llvm`` and the LLVM path above. The runner and Twister
both treat compiler warnings as errors.

Sanitizers and negative controls
*******************************

.. code-block:: bash

   uv run "$app/run.py" --zephyr "$source_tree" \
     --sanitize --output /tmp/npm13xx-sanitized
   uv run "$app/negative.py" --zephyr "$source_tree" \
     --output /tmp/npm13xx-negative

The sanitizer run enables ASan, UBSan and leak detection, shuffles the tests
and repeats each variant's suite ten times. It runs the executable through
``setarch -R`` to avoid a shadow-memory collision on hosts with wide ASLR.
This changes only that process. A container needs permission for
``personality`` and leak-sanitizer tracing; the recorded Podman invocation uses
``--security-opt=seccomp=unconfined --cap-add=SYS_PTRACE``. A startup failure
is a failure, not a sanitizer pass. Leak detection is not disabled.

The six negative controls change traversal, clear order, re-registration,
undefined masks, registration ordering and registration error propagation.
Each must configure and build successfully, then exit nonzero at its designated
assertion. They execute nPM1300 under GCC and leave disposable worktrees and
logs in the chosen output directory. A compiler failure does not count.

The runners write commands, configure/build/run exit codes and results JSON.
``recorded-results.json`` summarizes the recorded executions. Ordinary positive
tests and expected mutant failures are recorded separately.

Limits
******

No PMIC hardware run is included. External list changes must be serialized
with dispatch; these tests do not establish arbitrary concurrent add/remove
safety or exactly-once event delivery. Successful native tests do not validate
PMIC electrical behavior. Shield sample results are build-only. These external
tests are not part of the production PR's GitHub CI test plan.
