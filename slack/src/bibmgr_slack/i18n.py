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


JA_DIAGNOSTIC_DESCRIPTIONS = {
    "BIB-SYNTAX-001": "同じフィールドが1つのエントリ内で重複しています。",
    "BIB-SYNTAX-002": "フィールド名の大文字・小文字がプロファイルの指定と一致していません。",
    "BIB-SYNTAX-003": "フィールドの並び順がプロファイルの指定と一致していません。",
    "BIB-SYNTAX-004": "最後のフィールドに末尾のカンマが必要です。",
    "BIB-SYNTAX-005": "フィールド値を波括弧で囲む必要があります。",
    "BIB-SYNTAX-006": "等号の両側には空白が1つずつ必要です。",
    "BIB-SYNTAX-007": "パーセントコメントはエントリ間に置く必要があります。",
    "BIB-SYNTAX-008": "TeXの特殊文字をエスケープする必要があります。",
    "BIB-SYNTAX-009": "フィールド値内の改行を正規化する必要があります。",
    "BIB-SYNTAX-101": "BibTeXの構文を解釈できません。",
    "BIB-SYNTAX-102": "エントリに引用キーが必要です。",
    "BIB-SYNTAX-103": "フィールド間の区切りが不足しています。",
    "BIB-SYNTAX-104": "フィールド名を解釈できません。",
    "BIB-SYNTAX-105": "フィールド値が空です。",
    "BIB-SYNTAX-106": "フィールド値の形式を解釈できません。",
    "BIB-SYNTAX-107": "フィールドの境界が正しくありません。",
    "BIB-SYNTAX-108": "フィールド値の境界が正しくありません。",
    "BIB-SYNTAX-109": "エントリが閉じられていません。",
    "BIB-SYNTAX-110": "波括弧で囲んだ値が閉じられていません。",
    "BIB-SYNTAX-111": "引用符で囲んだ値が閉じられていません。",
    "BIB-SYNTAX-112": "BibTeXパーサーが入力を処理できませんでした。",
    "BIB-SEMANTIC-001": "DOIが有効な形式ではないか、表記の正規化が必要です。",
    "BIB-SEMANTIC-002": "arXiv識別子が有効な形式ではないか、表記の正規化が必要です。",
    "BIB-SEMANTIC-003": "書誌情報として必須のデータが不足しています。",
    "BIB-SEMANTIC-004": "エントリ種別が掲載先の種別と一致していません。",
    "BIB-SEMANTIC-005": "同じエントリ内に競合する識別子があります。",
    "BIB-SEMANTIC-006": "著者情報を一意に解釈できません。",
    "BIB-SEMANTIC-007": "出版日が有効な形式ではないか、日付フィールド間で値が競合しています。",
    "BIB-SEMANTIC-008": "書誌情報の値が未解決または競合しています。",
    "BIB-SEMANTIC-009": "同じ引用キーが複数のエントリで使用されています。",
    "BIB-SEMANTIC-010": "同じDOIが複数のエントリで使用されています。",
    "BIB-SEMANTIC-011": "同じarXiv識別子が複数のエントリで使用されています。",
    "BIB-SEMANTIC-012": "リポジトリ名またはその識別子が登録ルールに適合していません。",
    "BIB-SEMANTIC-101": "未定義のBibTeX文字列マクロが参照されています。",
    "BIB-SEMANTIC-102": "BibTeX文字列マクロの展開結果を一意に決定できません。",
    "BIB-SEMANTIC-106": "URLはhttp://またはhttps://で始まる有効な絶対URLである必要があります。",
    "LAB-KEY-002": "引用キーがプロファイルで指定された形式と一致していません。",
    "LAB-ENTRY-003": "エントリ種別に応じた必須フィールドが不足しています。",
    "LAB-ENTRY-004": "このプロファイルでは使用できないフィールドが含まれています。",
    "LAB-ARXIV-001": "arXiv情報の表現方法がプロファイルの指定と一致していません。",
    "LAB-URL-001": "URLフィールドがプロファイルのURL保持ルールと一致していません。",
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
            message = JA_DIAGNOSTIC_DESCRIPTIONS.get(
                code, self.text("diagnostic_generic")
            )
        return f"[{code}] {message}"

    def export_warning(self, warning: dict[str, Any]) -> str:
        if self.language == "en":
            return str(warning.get("message") or self.text("warning_generic"))
        return self.text("warning_generic")
