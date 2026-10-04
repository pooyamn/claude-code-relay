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


if __name__ == '__main__': unittest.main()
