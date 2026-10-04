"""Offline PC acceptance: inspect selected ASTs, never import hardware scripts."""
import ast
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path('/Users/pouya/oracova-bench')


@unittest.skipUnless((ROOT / 'daptls.py').is_file(), 'Requires the restored private PC bench payload')
class BenchLinuxPorts(unittest.TestCase):
    def tree(self, name):
        return ast.parse((ROOT / name).read_text())

    def assignment(self, name, variable):
        return next(node.value for node in self.tree(name).body if isinstance(node, ast.Assign) and
                    any(isinstance(target, ast.Name) and target.id == variable for target in node.targets))

    def globals(self, environment=None, platform='linux'):
        return {'os': SimpleNamespace(environ=environment or {}, path=os.path),
                'sys': SimpleNamespace(platform=platform)}

    def test_three_tls_helpers_use_linux_openssl_and_preserve_ca_verification(self):
        for name in ['daptls.py', 'tlsconsole.py', 'tlscmd.py']:
            expression = compile(ast.Expression(self.assignment(name, 'OPENSSL')), name, 'eval')
            self.assertEqual(eval(expression, self.globals()), '/usr/bin/openssl')
            self.assertEqual(eval(expression, self.globals({'BENCH_OPENSSL': '/reviewed/openssl'})), '/reviewed/openssl')
            strings = [node.value for node in ast.walk(self.tree(name)) if isinstance(node, ast.Constant)]
            self.assertIn('-verify_return_error', strings); self.assertIn('-tls1_3', strings)
            self.assertIn('-CAfile', strings)

    def test_stamp_uses_preserved_local_image_key_without_loading_or_signing(self):
        tree = self.tree('stamp.py')
        opening = next(node for node in ast.walk(tree) if isinstance(node, ast.Call) and
                       isinstance(node.func, ast.Name) and node.func.id == 'open' and
                       isinstance(node.args[0], ast.Call))
        expression = compile(ast.Expression(opening.args[0]), 'stamp.py', 'eval')
        self.assertEqual(eval(expression, self.globals({'BENCH_KEYS_DIR': str(ROOT / 'keys')})), str(ROOT / 'keys/dev.pem'))

    def test_power_requires_pc_hub_mapping_before_spawning_anything(self):
        definition = next(node for node in self.tree('pl_lib.py').body if isinstance(node, ast.FunctionDef) and node.name == 'power')
        code = compile(ast.Module(body=[definition], type_ignores=[]), 'pl_lib.py', 'exec')
        namespace = self.globals(); runner = Mock(return_value=SimpleNamespace(returncode=0))
        namespace.update(subprocess=SimpleNamespace(run=runner), UH='/usr/bin/uhubctl')
        exec(code, namespace)
        with self.assertRaisesRegex(RuntimeError, 'reviewed PC'): namespace['power'](0)
        runner.assert_not_called()
        namespace['os'].environ = {'BENCH_USB_HUB': 'reviewed-hub', 'BENCH_USB_PORTS': 'reviewed-ports'}
        self.assertEqual(namespace['power'](1), 0)
        self.assertEqual(runner.call_args.args[0], ['/usr/bin/uhubctl', '-l', 'reviewed-hub', '-p', 'reviewed-ports', '-a', '1'])

    def test_linux_hub_tool_is_the_pinned_local_build(self):
        expression = compile(ast.Expression(self.assignment('pl_lib.py', 'UH')), 'pl_lib.py', 'eval')
        namespace = self.globals(); namespace['__file__'] = str(ROOT / 'pl_lib.py')
        self.assertEqual(eval(expression, namespace), str(ROOT / 'bin/uhubctl'))
        self.assertEqual(subprocess.run([str(ROOT / 'bin/uhubctl'), '--version'], capture_output=True, timeout=5).stdout.strip(), b'2.6.0')

    def test_wrapper_preserves_quoted_override_without_running_openocd(self):
        result = subprocess.run(['/bin/sh', str(ROOT / 'bin/openocd'), '%s', 'PC-WRAPPER-OK'],
                                env={'BENCH_OPENOCD': '/usr/bin/printf'}, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0); self.assertEqual(result.stdout, b'PC-WRAPPER-OK')

    def test_linux_benchmark_is_elf_and_original_darwin_binary_preserved(self):
        self.assertEqual((ROOT / 'bin/dapbench').read_bytes()[:4], b'\x7fELF')
        self.assertNotEqual((ROOT / 'dapbench').read_bytes()[:4], b'\x7fELF')
        self.assertEqual((ROOT / 'bin/dapbench').stat().st_mode & 0o777, 0o700)

    def test_all_top_level_python_helpers_parse_without_execution(self):
        for path in ROOT.glob('*.py'):
            ast.parse(path.read_text(), filename=str(path))

    def test_default_openocd_accepts_tcp_configuration_without_init_or_hardware(self):
        result = subprocess.run([str(ROOT / 'bin/openocd'), '-f', '/dev/null',
                                 '-c', 'adapter driver cmsis-dap', '-c', 'cmsis-dap backend tcp',
                                 '-c', 'cmsis-dap tcp host 127.0.0.1', '-c', 'cmsis-dap tcp port 1',
                                 '-c', 'echo PC-TCP-CONFIG-PASS', '-c', 'shutdown'], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'PC-TCP-CONFIG-PASS', result.stdout + result.stderr)

    def test_supervisor_binary_and_original_backup(self):
        self.assertEqual(Path('/Users/pouya/supervisor-tools/dapbench').read_bytes()[:4], b'\x7fELF')
        self.assertEqual(Path('/Users/pouya/supervisor-tools/dapbench').stat().st_mode & 0o777, 0o700)
        self.assertNotEqual(Path('/Users/pouya/.migration/bench-tools-BSgEcASg/supervisor-dapbench-macos-original').read_bytes()[:4], b'\x7fELF')

    def test_shell_ports_parse_without_running_recovery(self):
        for path in [ROOT / 'probe_gate.sh', Path('/Users/pouya/supervisor-tools/probe_gate.sh'),
                     Path('/Users/pouya/supervisor-tools/stlink_recover.sh')]:
            result = subprocess.run(['/bin/zsh', '-n', str(path)], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_supervisor_usb_recovery_refuses_unmapped_pc_before_any_action(self):
        environment = {'PATH': '/usr/bin:/bin', 'HOME': '/Users/pouya'}
        power = subprocess.run(['/bin/zsh', '/Users/pouya/supervisor-tools/stlink_recover.sh'],
                               env=environment, capture_output=True, timeout=5)
        self.assertEqual(power.returncode, 2); self.assertIn(b'no hub action', power.stderr)
        reset = subprocess.run(['/usr/bin/python3', '/Users/pouya/supervisor-tools/usbreset.py'],
                               env=environment, capture_output=True, timeout=5)
        self.assertNotEqual(reset.returncode, 0); self.assertIn(b'no device was reset', reset.stderr)
        tree = ast.parse(Path('/Users/pouya/supervisor-tools/usbreset.py').read_text())
        constants = {n.targets[0].id: n.value.value for n in tree.body if isinstance(n, ast.Assign) and
                     isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)}
        self.assertEqual(constants['COOLDOWN_S'], 90); self.assertEqual(constants['MAX_PER_HOUR'], 4)
        self.assertIn('!= DEVICE_SERIAL', Path('/Users/pouya/supervisor-tools/usbreset.py').read_text())


if __name__ == '__main__': unittest.main()
