"""User-facing English and Japanese messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MESSAGES = {
    "en": {
        "usage_mention": "Mention me with exactly one BibTeX entry in a code block.",
        "usage_direct": "Send exactly one BibTeX entry in a code block.",
        "input_too_large": "The BibTeX entry is too large. The limit is {limit} bytes.",
        "invalid_syntax": "The code block is not valid BibTeX, so it cannot be exported.{codes}",
        "record_count": "Enter exactly one BibTeX entry. Found {count} entries.",
        "choose_profile": "Choose an export profile for this BibTeX entry.",
        "choose_placeholder": "Choose a profile",
        "expired": "This export request has expired. Submit the BibTeX entry again.",
        "wrong_user": "Only the user who submitted the BibTeX entry can choose its profile.",
        "unknown_profile": "That export profile is not available. Submit the BibTeX entry again to refresh the list.",
        "export_failed": "The entry could not be exported deterministically. Check it for conflicting or unresolved values.",
        "exported": "Exported with the `{profile}` profile.",
        "fixes": "Applied {count} safe fixes, including lint fixes.",
        "remaining": "Remaining validation findings ({count}); export continued:",
        "serializer_warnings": "Export warnings ({count}):",
        "diagnostic_generic": "The entry does not satisfy the selected validation rule.",
        "warning_generic": "Some information could not be represented completely.",
    },
    "ja": {
        "usage_mention": "BibTeXエントリを1件だけコードブロックに入れてメンションしてください。",
        "usage_direct": "BibTeXエントリを1件だけコードブロックに入れて送信してください。",
        "input_too_large": "BibTeXエントリが大きすぎます。上限は{limit}バイトです。",
        "invalid_syntax": "コードブロックが正しいBibTeXではないため、出力できません。{codes}",
        "record_count": "BibTeXエントリを1件だけ入力してください。{count}件検出しました。",
        "choose_profile": "このBibTeXエントリの出力プロファイルを選択してください。",
        "choose_placeholder": "プロファイルを選択",
        "expired": "この出力リクエストは期限切れです。BibTeXエントリを再度送信してください。",
        "wrong_user": "プロファイルを選択できるのはBibTeXエントリを送信したユーザーだけです。",
        "unknown_profile": "その出力プロファイルは利用できません。BibTeXエントリを再度送信して一覧を更新してください。",
        "export_failed": "値の競合または未解決項目があるため、エントリを一意に出力できませんでした。",
        "exported": "`{profile}`プロファイルで出力しました。",
        "fixes": "lintを含む安全な修正を{count}件適用しました。",
        "remaining": "未解決の検証項目が{count}件ありますが、出力を継続しました：",
        "serializer_warnings": "出力時の警告が{count}件あります：",
        "diagnostic_generic": "選択した検証ルールに適合していません。",
        "warning_generic": "一部の情報を完全には表現できませんでした。",
    },
}


@dataclass(frozen=True)
class Translator:
    language: str

    def text(self, key: str, **values: Any) -> str:
        return MESSAGES[self.language][key].format(**values)

    def diagnostic(self, diagnostic: dict[str, Any]) -> str:
        code = str(diagnostic.get("code", "BIB-UNKNOWN"))
        if self.language == "en":
            message = str(
                diagnostic.get("message") or self.text("diagnostic_generic")
            )
        else:
            message = self.text("diagnostic_generic")
        return f"[{code}] {message}"

    def export_warning(self, warning: dict[str, Any]) -> str:
        if self.language == "en":
            return str(warning.get("message") or self.text("warning_generic"))
        return self.text("warning_generic")
