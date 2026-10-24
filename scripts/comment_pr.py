"""Post or update the `cdk diff` comment on the pull request that triggered this CodeBuild run."""

import json
import os
import sys
import urllib.request

REPO = "Pro100Sergosha/investigation-engine"
MARKER = "<!-- cdk-diff -->"
LIMIT = 60_000  # GitHub caps a comment at 65,536 characters


def body(diff: str, succeeded: bool, build_url: str) -> str:
    status = "succeeded" if succeeded else "FAILED"
    if len(diff) > LIMIT:
        diff = diff[:LIMIT] + "\n... truncated, read the build log"
    return (
        f"{MARKER}\n### `cdk diff` against production: {status}\n\n"
        f"```\n{diff}\n```\n[CodeBuild log]({build_url})"
    )


def _api(method: str, path: str, payload: dict | None = None):
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        data=json.dumps(payload).encode() if payload else None,
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main(diff_path: str) -> None:
    trigger = os.environ.get("CODEBUILD_WEBHOOK_TRIGGER", "")  # "pr/12" for pull requests
    if not trigger.startswith("pr/"):
        print(f"not a pull request build ({trigger!r}), no comment")
        return
    pr = trigger.removeprefix("pr/")
    try:
        with open(diff_path, encoding="utf-8", errors="replace") as f:
            diff = f.read()
    except FileNotFoundError:
        diff = "cdk diff did not run, read the build log"
    text = body(
        diff,
        succeeded=os.environ.get("CODEBUILD_BUILD_SUCCEEDING") == "1",
        build_url=os.environ.get("CODEBUILD_BUILD_URL", ""),
    )
    # One comment per PR, edited on every push, instead of a new comment each time.
    comments = _api("GET", f"/repos/{REPO}/issues/{pr}/comments?per_page=100")
    ours = [c for c in comments if c["body"].startswith(MARKER)]
    if ours:
        _api("PATCH", f"/repos/{REPO}/issues/comments/{ours[-1]['id']}", {"body": text})
    else:
        _api("POST", f"/repos/{REPO}/issues/{pr}/comments", {"body": text})


if __name__ == "__main__":
    main(sys.argv[1])
