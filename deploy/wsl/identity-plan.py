#!/usr/bin/env python3
"""Render an identity preparation plan, never apply it or activate services.

Existing account/UID/group collisions fail instead of repurposing identities.
The target acceptance run still has to check ACLs, memberships, cgroups, native
runtime/subscription isolation and app continuity. Do not treat a plan as proof.
"""
import argparse
import grp
import json
from pathlib import Path
import pwd
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from relay_core.identity import Denied, Policy, strict_json
from relay_core.binding_reads import BindingReadPolicy
from relay_core.owner_gate import OwnerPolicy
from relay_core.artifacts import DeploymentPolicy
from relay_core.intake import IntakePolicy


def plan(folder, users=None, groups=None):
    users = list(pwd.getpwall()) if users is None else users
    groups = list(grp.getgrall()) if groups is None else groups
    folder = Path(folder)
    raw = strict_json((folder / "identities/broker-policy.json.example").read_bytes())
    policy = Policy(raw)
    binding_read_policy = BindingReadPolicy(strict_json((folder / "identities/binding-read-policy.json.example").read_bytes()), policy)
    owner_policy = OwnerPolicy(strict_json((folder / "identities/owner-policy.json.example").read_bytes()), policy)
    deployment_policy = DeploymentPolicy(strict_json((folder / "identities/deployment-policy.json.example").read_bytes()))
    intake_policy = IntakePolicy(strict_json((folder / "identities/intake-policy.json.example").read_bytes()), owner_policy, policy)
    accounts, shared_groups, memberships = {}, {}, []
    for line in (folder / "identities/ccrelay.sysusers.conf").read_text().splitlines():
        fields = shlex.split(line, comments=True)
        if not fields:
            continue
        if fields[0] == "u" and len(fields) == 6:
            name, uid, _, home, shell = fields[1:]
            if name in accounts or not uid.isdigit() or shell != "/usr/sbin/nologin" or not home.startswith("/var/lib/ccrelay"):
                raise Denied("unsafe identity template")
            accounts[name] = {"uid": int(uid), "home": home, "shell": shell}
        elif fields[0] == "g" and len(fields) == 3:
            shared_groups[fields[1]] = int(fields[2])
        elif fields[0] == "m" and len(fields) == 3:
            memberships.append(fields[1:])
        else:
            raise Denied("unsupported sysusers template directive")
    if len({item["uid"] for item in accounts.values()}) != len(accounts):
        raise Denied("UID alias in identity template")
    for name, target in accounts.items():
        for current in users:
            if current.pw_name == name or current.pw_uid == target["uid"]:
                if (current.pw_name, current.pw_uid, current.pw_gid, current.pw_dir, current.pw_shell) != \
                        (name, target["uid"], target["uid"], target["home"], target["shell"]):
                    raise Denied("existing account conflicts with identity plan")
        for current in groups:
            if current.gr_name == name or current.gr_gid == target["uid"]:
                if (current.gr_name, current.gr_gid, current.gr_mem) != (name, target["uid"], []):
                    raise Denied("private role/component group conflict")
    for name, gid in shared_groups.items():
        if gid in {item["uid"] for item in accounts.values()}:
            raise Denied("shared group aliases a private identity")
        allowed = {user for user, group in memberships if group == name}
        for current in groups:
            if current.gr_name == name or current.gr_gid == gid:
                if current.gr_name != name or current.gr_gid != gid or not set(current.gr_mem).issubset(allowed):
                    raise Denied("unexpected shared-group members")
    if accounts.get("ccrelay-broker", {}).get("uid") != policy.broker_uid or shared_groups.get("ccrelay-clients") != policy.client_gid:
        raise Denied("broker policy and OS identity templates differ")
    for uid in binding_read_policy.readers:
        if uid == 0:
            continue
        readers = [name for name, item in accounts.items() if item["uid"] == uid]
        if len(readers) != 1 or [readers[0], "ccrelay-clients"] not in memberships:
            raise Denied("binding reader is not a planned component with explicit socket access")
    if accounts.get("relay", {}).get("uid") != owner_policy.ingress_uid or \
            accounts.get("ccrelay-deployer", {}).get("uid") != owner_policy.gate_uid or \
            {user for user, group in memberships if group == "ccrelay-owner-ingress"} != {"relay", "ccrelay-deployer"}:
        raise Denied("owner ingress policy and OS identity templates differ")
    for role_id, role in policy.roles.items():
        if accounts.get("ccrelay-" + role_id, {}).get("uid") != role.fields["uid"]:
            raise Denied("role policy and OS identity templates differ")
    role_names = {"ccrelay-" + role_id for role_id in policy.roles}
    privileged = {"sudo", "wheel", "docker", "lxd", "disk", "adm", "systemd-journal"}
    for group in groups:
        if (group.gr_name in privileged or group.gr_name in accounts) and role_names.intersection(group.gr_mem):
            raise Denied("worker has privileged or another identity's supplementary group")
    return {"schema": "ccrelay.identity_plan.v1", "mode": "dry-run-only", "policy_digest": policy.digest,
            "owner_policy_digest": owner_policy.digest, "deployment_policy_digest": deployment_policy.digest,
            "intake_policy_digest": intake_policy.digest,
            "binding_read_policy_digest": binding_read_policy.digest, "binding_read_enabled": binding_read_policy.enabled,
            "owner_ingress_enabled": owner_policy.enabled, "bootstrap_deployment_enabled": deployment_policy.bootstrap_enabled,
            "accounts": accounts, "shared_groups": shared_groups, "memberships": memberships,
            "changes_applied": False, "services_enabled": False,
            "pending": ["owner-reviewed artifacts and target permission tests", "per-role native login/app topology",
                        "trusted PR 7 launcher", "PR 3 deployment authorization", "PR 20 cutover"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", required=True)
    args = parser.parse_args()
    print(json.dumps(plan(Path(__file__).resolve().parent), indent=2))


if __name__ == "__main__":
    main()
