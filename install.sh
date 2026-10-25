#!/usr/bin/env bash
set -euo pipefail

repo="https://github.com/xingyun7842/weread-optimizer.git"
skill_dir="${HOME}/.codex/skills/weread-optimizer"

mkdir -p "$(dirname "$skill_dir")"

if [ -d "$skill_dir/.git" ]; then
  echo "Updating existing skill at $skill_dir"
  git -C "$skill_dir" pull --ff-only
elif [ -e "$skill_dir" ]; then
  echo "Path exists but is not a git repo: $skill_dir" >&2
  exit 1
else
  echo "Installing skill to $skill_dir"
  git clone "$repo" "$skill_dir"
fi

if command -v python3 >/dev/null 2>&1; then
  python3 -m pip install -r "$skill_dir/requirements.txt"
elif command -v python >/dev/null 2>&1; then
  python -m pip install -r "$skill_dir/requirements.txt"
else
  echo "Python was not found. Install Python, then run: python -m pip install -r $skill_dir/requirements.txt" >&2
fi

echo "Installed weread-optimizer"
