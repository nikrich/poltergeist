#!/usr/bin/env bash
# One-command release bump for Poltergeist.
#
# release-please is unreliable in this repo (it stalls and stops opening release
# PRs). The release workflow has a fallback that cuts the tag + GitHub release +
# builds from the manifest version whenever HEAD is a "chore: release" commit —
# this script prepares exactly that commit.
#
# It bumps the manifest + package.json, generates a CHANGELOG section from the
# conventional commits since the last tag, and commits. It does NOT push — review
# the commit, then run the printed `git push` to actually cut the release.
#
# Usage:  scripts/release.sh <version>     e.g.  scripts/release.sh 0.4.2
set -euo pipefail

version="${1:-}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: scripts/release.sh <X.Y.Z>   (e.g. 0.4.2)" >&2
  exit 1
fi

root="$(git rev-parse --show-toplevel)"
cd "$root"

branch="$(git branch --show-current)"
if [[ "$branch" != "main" ]]; then
  echo "error: run on main (you are on '$branch')" >&2
  exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: working tree is dirty — commit or stash first" >&2
  exit 1
fi

git pull --ff-only origin main
git fetch --tags --force origin   # ensure the previous release tag is local so
                                  # the CHANGELOG "since last release" range resolves

tag="v${version}"
if git rev-parse "$tag" >/dev/null 2>&1; then
  echo "error: tag $tag already exists" >&2
  exit 1
fi

prev="$(python3 -c "import json;print(json.load(open('.release-please-manifest.json'))['desktop'])")"
echo "bumping ${prev} -> ${version}"

# 1) manifest + desktop/package.json
python3 - "$version" <<'PY'
import json, sys
v = sys.argv[1]
json.dump({"desktop": v}, open(".release-please-manifest.json", "w"), indent=2)
open(".release-please-manifest.json", "a").write("\n")
p = "desktop/package.json"
d = json.load(open(p))
d["version"] = v
json.dump(d, open(p, "w"), indent=2)
open(p, "a").write("\n")
PY

# 2) CHANGELOG section from conventional commits since the previous tag
range="v${prev}..HEAD"
git rev-parse "v${prev}" >/dev/null 2>&1 || range="HEAD"
python3 - "$version" "$prev" "$range" <<'PY'
import subprocess, sys, datetime
version, prev, rng = sys.argv[1], sys.argv[2], sys.argv[3]
log = subprocess.check_output(
    ["git", "log", "--no-merges", "--pretty=* %s", rng], text=True
).splitlines()
feats = [l for l in log if l.startswith("* feat")]
fixes = [l for l in log if l.startswith("* fix")]
perf  = [l for l in log if l.startswith("* perf")]
date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
url = "https://github.com/nikrich/poltergeist/compare/v%s...v%s" % (prev, version)
out = ["## [%s](%s) (%s)" % (version, url, date), ""]
for title, items in (("Features", feats), ("Bug Fixes", fixes), ("Performance", perf)):
    if items:
        out += ["", "### %s" % title, ""] + items
out += [""]
section = "\n".join(out) + "\n"
cl = open("desktop/CHANGELOG.md").read()
cl = cl.replace("# Changelog\n\n", "# Changelog\n\n" + section, 1)
open("desktop/CHANGELOG.md", "w").write(cl)
PY

git add .release-please-manifest.json desktop/package.json desktop/CHANGELOG.md
git commit -m "chore: release ${version}"

echo
echo "Prepared release commit for ${tag}. Review it:"
echo "    git show HEAD"
echo "Then push to cut the release (workflow builds + publishes ${tag}):"
echo "    git push origin HEAD:main"
