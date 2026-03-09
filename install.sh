#!/usr/bin/env bash
# install.sh — Security Agent for VS Code Copilot
# Usage: curl -sSL https://raw.githubusercontent.com/shahin99991/Security-Agent/main/install.sh | bash
# Or:    bash install.sh [target_dir]
#
# Installs the security-guard agent and prompt-injection-guard skill
# into the .github/ directory of your project.

set -euo pipefail

REPO="shahin99991/Security-Agent"
BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
TARGET="${1:-.}"

FILES=(
  ".github/agents/security-guard.agent.md"
  ".github/skills/prompt-injection-guard/SKILL.md"
  ".github/skills/prompt-injection-guard/references/attack-patterns.md"
  ".github/skills/prompt-injection-guard/references/sanitizer.py"
)

echo "🛡️  Security Agent Installer"
echo "Target directory: ${TARGET}"
echo ""

for file in "${FILES[@]}"; do
  dir="$(dirname "${TARGET}/${file}")"
  mkdir -p "${dir}"
  url="${BASE_URL}/${file}"
  dest="${TARGET}/${file}"

  if [ -f "${dest}" ]; then
    echo "⏭️  Skipped (already exists): ${file}"
  else
    echo "⬇️  Downloading: ${file}"
    curl -sSfL "${url}" -o "${dest}"
    echo "✅  Saved: ${dest}"
  fi
done

echo ""
echo "✨ Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Restart VS Code or reload the Copilot extension"
echo "  2. In Copilot Chat, type: @security-guard"
echo "  3. Paste external content to inspect it"
echo ""
echo "Docs: https://github.com/${REPO}"
