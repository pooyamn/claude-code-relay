# PC router release validation

Every push (including tags), pull request, published release and manual workflow
run executes `.github/workflows/pc-router-release-validation.yml`. Both Windows
and Linux publish their own self-contained artifact using the pinned SDK, then
run `pc-router/validate-release.ps1` against that executable. A failed publish,
missing regression suite, failed check or changed assembly fails the job.

The upload-timeout integration regression drives the real router through:

1. Confirmed incoming input and native completion producing an outgoing ZIP.
2. A Telegram upload timeout after durable outgoing-file intent is persisted.
3. Continued input and steering in unaffected Codex and Claude topics, including
   a different topic in the same forum and the same topic number in another forum.
4. Retaining affected-topic input without native dispatch.
5. Reopening SQLite and restarting the observer: the original upload remains
   unknown, active unrelated work reattaches to the exact turn, and no upload or
   native input is replayed.

The named fast suite is `--self-test-input-isolation`; it is also mandatory
inside `--self-test`. Thus existing deployers that run the complete candidate
self-test before stopping production automatically include this regression.
The standard `pc-router/deploy.ps1` explicitly runs the shared release gate
before stopping the service and again on the installed artifact before startup.
Historical one-off deployers running only a focused suite are not reusable
release gates: run `validate-release.ps1` on the actual candidate before any
maintenance fence or service stop. Preserve the independent Claude host and
native agents during routine router deployment.

For a Windows candidate in an isolated administrator test environment, without
production credentials (the full suite exercises real protected cache ACLs):

```powershell
dotnet publish pc-router/KhadangRouter/KhadangRouter.csproj -c Release -r win-x64 --self-contained true -o C:\Workspaces\router-candidate
./pc-router/validate-release.ps1 -CandidateDirectory C:\Workspaces\router-candidate
```

CI is validation, not deployment authority. It does not connect to production,
exercise a real Telegram round trip, run models, clear uncertain receipts or
restart services. Published-release validation reports failure; it does not
retroactively unpublish a release. Requiring the two status checks in GitHub
branch protection is a separate repository setting, not enabled by this file.
