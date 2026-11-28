"""Post-audit correction for prospective speech in otherwise eligible closing witnesses.

Read one raw family capture and return the frozen record plus the enactment check.
The original infer.py remains available for replay of the locked experiment.
"""
import argparse
import json
from pathlib import Path
import re

import infer


SENTENCE_BREAK = re.compile(r"(?<=[.!?;])(?:\s+|$)")
PREDICATE = re.compile(r"\b(?:cancel\w*|withdraw\w*|abandon\w*|sink|clos(?:e[ds]?|ing)|"
                       r"fail\w*|pass\w*|approv\w*|successful)\b", re.I)
NONASSERTION = re.compile(
    r"\b(?:will|would|could|should|might|may|must|ought|whether|unless|if|assuming|"
    r"hope\w*|expect\w*|suppos\w*|believ\w*|think|thinking|intend\w*|"
    r"plan(?:s|ned|ning)?|propos(?:e[ds]?|ing)|suggest\w*|aim(?:s|ed|ing)?|"
    r"want(?:s|ed)?|wish\w*|consider\w*|recommend\w*|request\w*|ask(?:s|ed|ing)?|"
    r"let['’]s|let\s+us|going\s+to|about\s+to|"
    r"need(?:s|ed)?\s+to|how\s+to|possible|possibly|potentially|likely)\b|"
    r"['’](?:ll|d)\b", re.I)
QUALIFIER = re.compile(r"^\s*[,:(-]?\s*(?:if|unless|when|tomorrow|next\s+(?:week|month)|"
                       r"subject\s+to|depending\s+on|provided\s+that|contingent\s+on)\b", re.I)


def is_enacted(witness, unquoted_body):
    """Require exact occurrence and no prospective or conditional setting at any occurrence.

    The matched quote can include a plan following an already enacted disposition,
    as in 'RC1 is closed and I will start a new vote'. Test modality only through
    the first disposition predicate, and test qualifications following the quote.
    Inputs use normalized, unquoted message body and a witness with a `quote` key.
    """
    quote = witness.get("quote") or ""
    if not quote:
        return False
    occurrences = list(re.finditer(re.escape(quote), unquoted_body, re.I))
    for occurrence in occurrences:
        left = SENTENCE_BREAK.split(unquoted_body[:occurrence.start()])[-1]
        right = SENTENCE_BREAK.split(unquoted_body[occurrence.end():], maxsplit=1)[0]
        predicate = PREDICATE.search(quote)
        prefix = left + quote[:predicate.start() if predicate else len(quote)]
        request = re.search(r"\bplease\s*$", prefix, re.I)
        if NONASSERTION.search(prefix) or request or QUALIFIER.search(right) or "?" in right or "?" in quote:
            return False
    return bool(occurrences)


def family_report_safe(family, variant="typed"):
    result = infer.family_report(family, variant)
    bodies = {m["url"]: infer.unquoted(m["body"]) for m in family["messages"]}
    for row in result["motions"]:
        enacted = []
        prospective = []
        for w in row["closing_witnesses"]:
            target = enacted if is_enacted(w, bodies[w["url"]]) else prospective
            target.append(w)
        row["excluded_closing_witnesses"] = prospective
        row["closing_witnesses"] = enacted
        signs = {w["value"] for w in enacted}
        row["outcome"] = next(iter(signs)) if len(signs) == 1 else ("conflict" if signs else "unknown")
        for scope in infer.REQUIRED:
            decision = infer.decide(row, scope, variant)
            decision["support"] = infer.selected_sources(row, scope, decision["action"])
            row[scope] = decision
    result["enactment_filter"] = "post-audit-1"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--variant", choices=("typed", "coupled", "untyped"), default="typed")
    args = parser.parse_args()
    print(json.dumps(family_report_safe(infer.read_capture(args.snapshot), args.variant), indent=2))
