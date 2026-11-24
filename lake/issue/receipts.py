from dataclasses import dataclass


@dataclass(frozen=True)
class IssueReceipt:
    request_id: str
    revision_id: str
    freeze_id: str


def make_issue_receipt(request_id: str, revision_id: str, freeze_id: str) -> IssueReceipt:
    return IssueReceipt(request_id, revision_id, freeze_id)


def match_issue_request(receipt: IssueReceipt, revision_id: str) -> IssueReceipt:
    if receipt.revision_id != revision_id:
        raise ValueError('issue request ID already binds a different revision')
    return receipt
