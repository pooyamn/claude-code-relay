"""Native response conformance only; no claim of OS or cross-client freshness."""
from copy import deepcopy
import unittest

from native_resume_fixtures import SETTINGS_DIGEST, resume_settings
from relay_core.contracts import fingerprint
from relay_core.identity import Denied
from relay_core.native_settings import permission_contract, verify_resume_permissions


class SettingsTests(unittest.TestCase):
    def result(self):
        return {**resume_settings(), "thread": {"id": "native-1", "sessionId": "unrelated-tree-root"}}

    def verify(self, value, **changes):
        arguments = dict(thread_id="native-1", worktree="/fixture/worktree", expected_digest=SETTINGS_DIGEST)
        arguments.update(changes)
        return verify_resume_permissions(value, **arguments)

    def test_full_native_response_is_distinct_from_requests_disk_config_and_tree_root(self):
        contract = self.verify(self.result())
        self.assertEqual(fingerprint(contract), SETTINGS_DIGEST)
        for value in ({"threadId": "native-1", "cwd": "/fixture/worktree"},
                      {"config": resume_settings()}, {"thread": {"id": "native-1"}}):
            with self.assertRaises(Denied):
                self.verify(value)

    def test_wrong_exact_thread_worktree_digest_or_missing_fields_fail_closed(self):
        for field in ("cwd", "approvalPolicy", "approvalsReviewer", "sandbox"):
            value = self.result()
            del value[field]
            with self.subTest(field=field), self.assertRaises(Denied):
                self.verify(value)
        for changes in ({"thread_id": "unrelated-tree-root"}, {"worktree": "/other"},
                        {"expected_digest": "version-1"}, {"expected_digest": "sha256:" + "a" * 64}):
            with self.subTest(changes=changes), self.assertRaises(Denied):
                self.verify(self.result(), **changes)

    def test_every_reported_permission_difference_invalidates_the_reviewed_pin(self):
        variants = ({"approvalPolicy": "on-request"}, {"approvalsReviewer": "auto_review"},
                    {"sandbox": {"type": "readOnly", "networkAccess": True}},
                    {"sandbox": {"type": "dangerFullAccess"}}, {"cwd": "/other"})
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises(Denied):
                self.verify({**self.result(), **changes})

    def test_pinned_workspace_defaults_and_root_order_have_one_contract(self):
        values = dict(cwd="/fixture/worktree", approval_policy="never", approvals_reviewer="user")
        first = permission_contract(**values, sandbox={"type": "workspaceWrite", "writableRoots": ["/z", "/a"]})
        second = permission_contract(**values, sandbox={"type": "workspaceWrite", "writableRoots": ["/a", "/z"],
                                    "networkAccess": False, "excludeTmpdirEnvVar": False, "excludeSlashTmp": False})
        self.assertEqual(first, second)
        self.assertNotEqual(first, permission_contract(**values, sandbox={"type": "workspaceWrite", "excludeSlashTmp": True}))

    def test_unknown_policy_fields_profiles_bad_flags_and_root_lists_have_no_fallback(self):
        variants = (None, {}, {"type": "future"}, {"type": "readOnly", "networkAccess": 1},
                    {"type": "readOnly", "readOnlyAccess": {"type": "restricted"}},
                    {"type": "dangerFullAccess", "networkAccess": False},
                    {"type": "externalSandbox", "networkAccess": []},
                    {"type": "workspaceWrite", "writableRoots": ["/a", "/a"]},
                    {"type": "workspaceWrite", "writableRoots": ["relative"]},
                    {"type": "workspaceWrite", "writableRoots": ["/a/../b"]},
                    {"type": "workspaceWrite", "writableRoots": "/a"},
                    {"type": "workspaceWrite", "writableRoots": ["/r" + str(i) for i in range(65)]})
        for sandbox in variants:
            with self.subTest(sandbox=sandbox), self.assertRaises(Denied):
                self.verify({**self.result(), "sandbox": sandbox})
        for profile in ({"id": ":workspace"}, {}, False):
            with self.subTest(profile=profile), self.assertRaises(Denied):
                self.verify({**self.result(), "activePermissionProfile": profile})
        for extra in ({"futurePermissions": {}}, {"runtimeWorkspaceRoots": ["/other"]}):
            with self.subTest(extra=extra), self.assertRaises(Denied):
                self.verify({**self.result(), **extra})

    def test_granular_approval_defaults_do_not_drop_permission_grant_flags(self):
        base = {"sandbox_approval": True, "rules": True, "mcp_elicitations": True}
        values = dict(cwd="/fixture/worktree", approvals_reviewer="user", sandbox={"type": "readOnly"})
        first = permission_contract(**values, approval_policy={"granular": base})
        second = permission_contract(**values, approval_policy={"granular": {**base, "skill_approval": False, "request_permissions": False}})
        self.assertEqual(first, second)
        self.assertNotEqual(first, permission_contract(**values, approval_policy={"granular": {**base, "request_permissions": True}}))
        for policy in ("future", True, {}, {"granular": {}}, {"granular": {**base, "rules": 1}},
                       {"granular": {**base, "future": False}}):
            with self.subTest(policy=policy), self.assertRaises(Denied):
                permission_contract(**values, approval_policy=policy)

    def test_verified_contract_does_not_alias_provider_mutable_objects(self):
        value = self.result()
        before = deepcopy(value)
        contract = self.verify(value)
        value["sandbox"]["networkAccess"] = True
        self.assertFalse(contract["sandbox"]["networkAccess"])
        self.assertEqual(self.verify(before), contract)

    def test_external_and_full_access_are_reported_not_rewritten_to_safer_defaults(self):
        values = dict(cwd="/fixture/worktree", approval_policy="untrusted", approvals_reviewer="user")
        for sandbox in ({"type": "dangerFullAccess"}, {"type": "externalSandbox", "networkAccess": "enabled"}):
            contract = permission_contract(**values, sandbox=sandbox)
            self.assertEqual(contract["sandbox"], sandbox)
            value = {**self.result(), "approvalPolicy": "untrusted", "sandbox": sandbox}
            self.assertEqual(self.verify(value, expected_digest=fingerprint(contract)), contract)

    def test_noncanonical_paths_and_unknown_approval_reviewers_are_not_defaulted(self):
        for cwd in ("relative", "/fixture//worktree", "/fixture/../other", "/fixture\\other", "/fixture/\nother"):
            with self.subTest(cwd=cwd), self.assertRaises(Denied):
                permission_contract(cwd=cwd, approval_policy="never", approvals_reviewer="user", sandbox={"type": "readOnly"})
        for reviewer in (None, "future", True):
            with self.subTest(reviewer=reviewer), self.assertRaises(Denied):
                permission_contract(cwd="/fixture/worktree", approval_policy="never", approvals_reviewer=reviewer, sandbox={"type": "readOnly"})
