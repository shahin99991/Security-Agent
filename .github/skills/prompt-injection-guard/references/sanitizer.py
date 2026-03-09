"""
prompt_injection_sanitizer.py

外部コンテンツの間接的プロンプトインジェクション検出・サニタイズユーティリティ。
VS Code Copilot Agent や Python スクリプトから import して使用する。

使い方:
    from sanitizer import scan, sanitize

    result = scan(fetched_text, source_url="https://example.com")
    if result.is_safe:
        process(result.sanitized_text)
    else:
        print(result.report())
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(Enum):
    HIGH = "🔴 HIGH"
    MEDIUM = "🟠 MEDIUM"
    LOW = "🟡 LOW"
    SAFE = "🟢 SAFE"


@dataclass
class Finding:
    risk: RiskLevel
    category: str
    snippet: str  # 該当箇所（最大100文字）
    line: int = 0


@dataclass
class ScanResult:
    source: str
    findings: list[Finding] = field(default_factory=list)
    sanitized_text: str = ""

    @property
    def is_safe(self) -> bool:
        return not any(f.risk == RiskLevel.HIGH for f in self.findings)

    @property
    def highest_risk(self) -> RiskLevel:
        if any(f.risk == RiskLevel.HIGH for f in self.findings):
            return RiskLevel.HIGH
        if any(f.risk == RiskLevel.MEDIUM for f in self.findings):
            return RiskLevel.MEDIUM
        if any(f.risk == RiskLevel.LOW for f in self.findings):
            return RiskLevel.LOW
        return RiskLevel.SAFE

    def report(self) -> str:
        lines = [
            "## 🔍 インジェクション検査結果",
            f"**ソース**: {self.source}",
            f"**判定**: {self.highest_risk.value}",
            "",
        ]
        if self.findings:
            lines += [
                "### 検出された問題",
                "| 危険度 | 種別 | 該当箇所 |",
                "|--------|------|---------|",
            ]
            for f in self.findings:
                snippet = f.snippet[:80].replace("\n", " ")
                lines.append(f"| {f.risk.value} | {f.category} | `{snippet}` |")
        else:
            lines.append("問題は検出されませんでした。")

        lines += [
            "",
            f"### 推奨アクション",
            f"- エージェントへの渡し可否: {'✅ 可' if self.is_safe else '⛔ 不可（要確認）'}",
        ]
        return "\n".join(lines)


# ─────────────────────────────────────────────
# 検出パターン定義
# ─────────────────────────────────────────────

_HIGH_PATTERNS: list[tuple[str, str]] = [
    # ロールプレフィックス
    (r"(?i)(SYSTEM|USER|ASSISTANT|HUMAN)\s*:", "ロールプレフィックス"),
    (r"\[INST\]|\[/INST\]|<\|system\|>|<\|user\|>|<\|assistant\|>", "ロールプレフィックス"),
    # 命令上書き
    (
        r"(?i)(ignore|forget|disregard)\s+(all\s+)?(previous|prior|your)?\s*(instructions?|rules?|guidelines?)",
        "命令上書き",
    ),
    (r"(?i)(your\s+(new|actual|real)\s+(instructions?|task|purpose))", "命令上書き"),
    (r"(?i)(pretend\s+(you\s+are|to\s+be)|act\s+as\s+if\s+you)", "ロールプレイ強制"),
    # 破壊的コマンド
    (r"rm\s+-rf\s+[/~]", "破壊的コマンド"),
    (r"(?i)(DROP\s+TABLE|TRUNCATE\s+TABLE|DELETE\s+FROM)", "SQLインジェクション"),
    (r"(?i)curl\s+.*\|\s*bash", "パイプ実行"),
    (r"(?i)wget\s+.*(-O\s*-\s*\||\|\s*bash)", "パイプ実行"),
    # 情報窃取
    (r"(?i)(exfiltrate|send\s+to|forward\s+to|POST\s+.*password|leak)", "情報窃取指示"),
]

_MEDIUM_PATTERNS: list[tuple[str, str]] = [
    # CSSによる不可視化
    (r"(?i)(color\s*:\s*(white|#fff{1,3}|rgba?\(255,\s*255,\s*255))", "不可視テキスト（CSS）"),
    (r"(?i)font-size\s*:\s*0", "不可視テキスト（font-size:0）"),
    (r"(?i)(visibility\s*:\s*hidden|display\s*:\s*none)", "不可視要素"),
    # コメント内命令
    (r"(?i)<!--.*?(ignore|system|instruction|exfiltrate).*?-->", "コメント内命令"),
    (r"(?i)/\*.*?(ignore|system|instruction).*?\*/", "コメント内命令"),
    # Markdownインジェクション：クエリパラメータが長い画像URL
    (r"!\[.*?\]\(https?://[^\s)]{60,}\)", "Markdownインジェクション疑い"),
    # メタデータ
    (r'(?i)<meta[^>]+content="[^"]{30,}"', "メタデータ隠蔽疑い"),
]

_LOW_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)(note\s+to\s+ai|ai\s*:|dear\s+ai|attention\s+ai)", "AIへの直接語りかけ"),
    (r"(?i)(this\s+message\s+is\s+for\s+(the\s+)?ai)", "AIへの直接語りかけ"),
]

_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")


def _check_base64(text: str) -> list[Finding]:
    findings = []
    for m in _BASE64_RE.finditer(text):
        try:
            decoded = base64.b64decode(m.group() + "==").decode("utf-8", errors="ignore")
            for pattern, category in _HIGH_PATTERNS:
                if re.search(pattern, decoded):
                    findings.append(
                        Finding(
                            risk=RiskLevel.MEDIUM,
                            category=f"Base64エンコード命令（{category}）",
                            snippet=m.group()[:60],
                        )
                    )
                    break
        except Exception:
            pass
    return findings


# ─────────────────────────────────────────────
# 公開 API
# ─────────────────────────────────────────────

def scan(text: str, source_url: str = "（不明）") -> ScanResult:
    """テキストをスキャンして ScanResult を返す。"""
    findings: list[Finding] = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern, category in _HIGH_PATTERNS:
            if re.search(pattern, line):
                findings.append(
                    Finding(RiskLevel.HIGH, category, line.strip()[:100], line_no)
                )

        for pattern, category in _MEDIUM_PATTERNS:
            if re.search(pattern, line, re.DOTALL):
                findings.append(
                    Finding(RiskLevel.MEDIUM, category, line.strip()[:100], line_no)
                )

        for pattern, category in _LOW_PATTERNS:
            if re.search(pattern, line):
                findings.append(
                    Finding(RiskLevel.LOW, category, line.strip()[:100], line_no)
                )

    findings.extend(_check_base64(text))

    sanitized = sanitize(text)
    return ScanResult(source=source_url, findings=findings, sanitized_text=sanitized)


def sanitize(text: str) -> str:
    """危険なパターンを [REMOVED] に置換したテキストを返す。"""
    result = text
    all_patterns = (
        [(p, c) for p, c in _HIGH_PATTERNS]
        + [(p, c) for p, c in _MEDIUM_PATTERNS]
    )
    for pattern, _ in all_patterns:
        result = re.sub(pattern, "[REMOVED]", result, flags=re.IGNORECASE | re.DOTALL)
    return result


# ─────────────────────────────────────────────
# CLI で直接実行する場合
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("使い方: python sanitizer.py <ファイルパスまたはURL>")
        sys.exit(1)

    target = sys.argv[1]

    if target.startswith("http"):
        import urllib.request
        with urllib.request.urlopen(target) as resp:  # noqa: S310
            content = resp.read().decode("utf-8", errors="ignore")
        source = target
    else:
        with open(target, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        source = target

    result = scan(content, source_url=source)
    print(result.report())

    if not result.is_safe:
        sys.exit(1)
