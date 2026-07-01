"""Static over-enumeration metrics for a set of GCL tier strings.

The PRIMARY response variable of the factorial is FACET BLOAT: how many alternatives
the model piles into a single `(+ ...)` OR-group. `max_terms_per_facet` is the headline
number (scouting ~13, the bloated shipped run ~30-50). Everything here is computed from
the GCL text alone -- no engine needed -- so the core result does not depend on a server.
"""

import re

_OPS = {"^", "+", "...", ">>", "<<", "#", "!>"}


def _or_group_bodies(gcl: str):
    """Yield the body text of every '(+ ... )' OR-group in `gcl` (balanced-paren scan)."""
    i = 0
    while True:
        j = gcl.find("(+", i)
        if j == -1:
            return
        depth = 0
        k = j
        while k < len(gcl):
            c = gcl[k]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        yield gcl[j + 2:k]  # text between "(+" and its matching ")"
        i = k + 1


def _count_operands(body: str) -> tuple:
    """(operand_count, quoted_phrase_count) for a '(+ ... )' body.

    A quoted phrase counts as one operand; nested groups are excluded (counted on their
    own); remaining whitespace tokens that are not GCL operators count one each.
    """
    phrases = re.findall(r'"[^"]*"', body)
    n_phrases = len(phrases)
    rest = re.sub(r'"[^"]*"', " ", body)     # drop quoted phrases
    rest = re.sub(r"\([^()]*\)", " ", rest)  # drop simple nested groups
    tokens = [t for t in rest.split() if t and t not in _OPS]
    return n_phrases + len(tokens), n_phrases


def analyze(tiers: list) -> dict:
    """`tiers`: list[str] of GCL. Returns the metrics dict."""
    sizes, phrase_counts, total_phrases = [], [], 0
    for gcl in tiers:
        for body in _or_group_bodies(gcl):
            n_ops, n_ph = _count_operands(body)
            sizes.append(n_ops)
            phrase_counts.append(n_ph)
            total_phrases += n_ph

    def mx(xs):
        return max(xs) if xs else 0

    def mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else 0

    joined = " ".join(tiers)
    return {
        "n_tiers": len(tiers),
        "n_facets": len(sizes),
        "max_terms_per_facet": mx(sizes),        # <-- headline bloat metric
        "mean_terms_per_facet": mean(sizes),
        "max_phrases_per_facet": mx(phrase_counts),
        "total_quoted_phrases": total_phrases,
        "total_gcl_chars": len(joined),
        "tier0_has_proximity": bool(tiers) and tiers[0].lstrip().startswith("(>>"),
    }


def entity_dropped(tiers: list, entity):
    """True if some tier OMITS the entity token (the entity-drop / transferable tier);
    None when the need has no named entity."""
    if not entity:
        return None
    return any(entity.lower() not in t.lower() for t in tiers)
