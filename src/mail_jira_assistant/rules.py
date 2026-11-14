"""Conservative transparent rules before AI; ambiguous responsibility stays with AI."""

import re
from email.utils import getaddresses

from .contracts import Classification


def non_action(subject, body, kind, recipients="", cc="", identity=()):
    rule = None
    if kind == "jira_notification":
        rule = "jira_notification_source"
    elif subject.lstrip().startswith("(광고)"):
        rule = "advertisement_subject_prefix"
    elif kind == "auto_notification":
        compact = re.sub(r"\s+", "", body)
        if any(
            marker in compact
            for marker in (
                "조치는필요하지않",
                "조치가필요하지않",
                "조치필요없",
                "준비과제는없",
            )
        ):
            rule = "automatic_notification_header"
        else:
            return None
    else:
        own = {x.casefold() for x in identity if "@" in x}
        direct = getaddresses([recipients])
        carbon = {address.casefold() for _, address in getaddresses([cc])}
        addressee = re.search(r"^\s*수신\s*[:：]\s*(.+?)\s*님\s*$", body, re.MULTILINE)
        if (
            own
            and any("@" not in alias for alias in identity)
            and own & carbon
            and not own & {a.casefold() for _, a in direct}
            and addressee
            and addressee[1].strip() in {name.strip() for name, _ in direct}
            and not any(alias.casefold() in body.casefold() for alias in identity)
        ):
            rule = "cc_explicit_other_addressee"
    if not rule:
        return None
    return rule, Classification(
        response_expected="no",
        action_required="no",
        work_performed="no",
        waiting_for_others="no",
        review_required=False,
        project_update_needed="no" if rule in ("advertisement_subject_prefix", "jira_notification_source") else "unknown",
        evidence=[],
        actions=[],
        missing_information=[],
    )
