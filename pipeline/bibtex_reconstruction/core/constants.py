from enum import Enum

class ProcessingStatus(str, Enum):
    SUCCESS = "success"
    NEEDS_REVIEW = "needs_review"
    API_ERROR = "api_error"
    NOT_FOUND = "not_found"

    @classmethod
    def determine_overall(cls, statuses: list["ProcessingStatus"]) -> "ProcessingStatus":
        """
        全体ステータスの優先順位判定:
        1. successが1つでもあればsuccess
        2. api_errorがあればapi_error (リトライ対象)
        3. needs_reviewがあればneeds_review
        4. すべてnot_foundならnot_found
        """
        status_set = set(statuses)
        if cls.SUCCESS in status_set:
            return cls.SUCCESS
        if cls.API_ERROR in status_set:
            return cls.API_ERROR
        if cls.NEEDS_REVIEW in status_set:
            return cls.NEEDS_REVIEW
        return cls.NOT_FOUND