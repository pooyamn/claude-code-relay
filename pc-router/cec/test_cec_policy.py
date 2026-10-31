"""Portable regression tests for the narrowly scoped Windows CEC policy."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parent
POLICY=(ROOT/'CEC-Policy.ps1').read_text()
INSTALL=(ROOT/'Install-CECPolicy.ps1').read_text()+(ROOT/'Register-CECTask.ps1').read_text()
HELPER=(ROOT/'CECClockGateProbe.cs').read_text()

class PolicyTests(unittest.TestCase):
    def test_only_target_data_write_is_cec_clock_gate(self):
        self.assertEqual(HELPER.count('Address(0x1e09);Out(0x4f,value);'),1)
        self.assertEqual(HELPER.count('Out(0x4f,value)'),1)
        self.assertIn('(current&0xfe)|savedBit',HELPER)

    def test_boot_and_resume_not_login(self):
        self.assertIn('New-ScheduledTaskTrigger -AtStartup',INSTALL)
        self.assertNotIn('-AtLogOn',INSTALL)
        for event in ('Power-Troubleshooter','EventID=1','Kernel-Power','EventID=107','EventID=507'):
            self.assertIn(event,INSTALL)
        self.assertIn('-UserId \'SYSTEM\' -LogonType ServiceAccount',INSTALL)
        self.assertIn("TypeNames.Add('Microsoft.Management.Infrastructure.CimInstance#MSFT_TaskTrigger')",INSTALL)
        self.assertIn('-Encoding Unicode',INSTALL)  # Export declares UTF-16.

    def test_no_unbounded_firmware_fighting(self):
        self.assertIn('-RestartCount 2',INSTALL)
        self.assertIn('TotalSeconds -lt 5',POLICY)
        self.assertNotRegex(POLICY,r'while\s*\(\s*\$true')

    def test_safety_and_integrity_checks(self):
        for guard in ('Get-FileHash','Get-AuthenticodeSignature','GuardIdle','GuardStable','CreateLease'):
            self.assertIn(guard,POLICY)
        self.assertIn('ReleaseDate.ToUniversalTime()',POLICY)
        self.assertIn('$manifest.driverSha256',POLICY)
        self.assertIn('SetClockGateBit(0)',POLICY)
        self.assertIn('Already gated; no control write',POLICY)

    def test_restore_disables_future_task_first(self):
        self.assertLess(POLICY.index('Disable-ScheduledTask'),POLICY.index('$probe.SetClockGateBit([int]$manifest.originalGateBit)'))

    def test_no_security_weakening_or_unrestricted_driver(self):
        self.assertNotIn('ExecutionPolicy Bypass',INSTALL+POLICY)
        self.assertNotIn('-unrestricted',INSTALL+POLICY)
        self.assertNotIn('bcdedit',INSTALL+POLICY)
        self.assertIn('/inheritance:r',INSTALL)

if __name__=='__main__': unittest.main(verbosity=2)
