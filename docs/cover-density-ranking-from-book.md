# Cover Density Ranking and Boolean Retrieval

> **Source:** Stefan Büttcher, Charles L. A. Clarke, Gordon V. Cormack,
> *Information Retrieval: Implementing and Evaluating Search Engines*, MIT Press, 2010.
> Chapter 2 ("Basic Techniques"), Sections 2.1 and 2.2.2–2.2.3 (pp. 33–66).
>
> This document extracts the **cover-based proximity ranking** method (known in the
> literature as *cover density ranking*; the book titles it "Proximity Ranking", §2.2.2)
> together with the **Boolean retrieval** method built on the same machinery (§2.2.3),
> plus every §2.1 dependency they rely on (the inverted-index ADT, phrase search,
> galloping search, the document/schema model, and the running-example tables).
>
> Math is rendered in LaTeX and algorithms as line-numbered pseudocode that matches the
> book's figures. Notation throughout: `next`/`prev` are the inverted-index ADT methods;
> $\langle t_1, t_2, \ldots, t_n\rangle$ is a term vector; intervals are written $[u, v]$;
> document-oriented positions are written $n{:}m$ (docid : offset).

---

## 1. The Inverted Index ADT (§2.1)

An inverted index provides a mapping between terms and their locations of occurrence in a
text collection $\mathcal{C}$. The **dictionary** lists the terms in the vocabulary $V$;
each term has a **postings list** of the positions at which it appears.

The book primarily uses a **schema-independent index**: postings are "flat" word positions
of individual term occurrences, not document identifiers, and the index makes no assumptions
about the structure (schema) of the underlying text.

The inverted index is defined as an abstract data type (ADT) with four methods:

- `first(t)` — returns the first position at which term $t$ occurs in the collection.
- `last(t)` — returns the last position at which $t$ occurs in the collection.
- `next(t, current)` — returns the position of $t$'s first occurrence **after** `current`.
- `prev(t, current)` — returns the position of $t$'s last occurrence **before** `current`.

Additional collection-level quantities:

- $l_t$ — the total number of times term $t$ appears in the collection (the length of its postings list).
- $l_{\mathcal{C}}$ — the length of the collection, so that $\sum_{t \in V} l_t = l_{\mathcal{C}}$ (where $V$ is the vocabulary).

**Worked values** (schema-independent index over Shakespeare's plays):

$$
\begin{aligned}
&\mathrm{first}(\text{“hurlyburly”}) = 316669 & &\mathrm{last}(\text{“thunder”}) = 1247139 \\
&\mathrm{first}(\text{“witching”}) = 265197 & &\mathrm{last}(\text{“witching”}) = 265197 \\
&\mathrm{next}(\text{“witch”}, 745429) = 745451 & &\mathrm{prev}(\text{“witch”}, 745451) = 745429 \\
&\mathrm{next}(\text{“hurlyburly”}, 345678) = 745434 & &\mathrm{prev}(\text{“hurlyburly”}, 456789) = 316669 \\
&\mathrm{next}(\text{“witch”}, 1245276) = \infty & &\mathrm{prev}(\text{“witch”}, 1598) = -\infty \\
&l_{\text{<PLAY>}} = 37 & &l_{\mathcal{C}} = 1271504 \\
&l_{\text{witching}} = 1
\end{aligned}
$$

**Boundary markers.** The symbols $-\infty$ and $\infty$ act as beginning-of-file and
end-of-file markers, representing positions beyond the beginning and end of the term
sequence. As a practical convention:

$$
\begin{aligned}
\mathrm{next}(t, -\infty) &= \mathrm{first}(t) & \mathrm{next}(t, \infty) &= \infty \\
\mathrm{prev}(t, \infty) &= \mathrm{last}(t) & \mathrm{prev}(t, -\infty) &= -\infty
\end{aligned}
$$

The methods permit both sequential and random access. A **sequential scan** of a postings
list is a simple loop:

```
current ← −∞
while current < ∞ do
    current ← next(t, current)
    do something with the current value
```

Many algorithms instead require random access, taking the result of a method call for one
term and applying it as an argument to a method call for another term, skipping through the
postings lists nonsequentially.

---

## 2. Extended Example: Phrase Search (§2.1.1)

This is the model the cover-finding and Boolean algorithms are adapted from. A phrase is a
list of terms; the goal is to identify the occurrences of the phrase in the collection.

A phrase occurrence is specified by an interval $[u, v]$, where $u$ indicates the start and
$v$ the end. (Interval notation is used for retrieval results throughout the book; an
interval may also be read as a stand-in for the text at that location.)

**Algorithm.** Given the phrase "$t_1\, t_2 \ldots t_n$" of $n$ terms, the algorithm works
through the postings lists left to right (one `next` call per term), then right to left
(one `prev` call per term). After each pass it has an interval in which the terms appear in
the correct order and as close together as possible. It then checks whether the terms are
adjacent: if so, an occurrence has been found; if not, it moves on.

```
nextPhrase (⟨t1 t2 ... tn⟩, position) ≡
1    v ← position
2    for i ← 1 to n do
3        v ← next(ti, v)
4    if v = ∞ then
5        return [∞, ∞]
6    u ← v
7    for i ← n − 1 down to 1 do
8        u ← prev(ti, u)
9    if v − u = n − 1 then
10       return [u, v]
11   else
12       return nextPhrase(⟨t1 t2 ... tn⟩, u)
```
*Figure 2.2 — Locates the first occurrence of a phrase after a given position. Calls the
`next` and `prev` methods and returns an interval.*

The loop over lines 2–3 locates the terms in order; at its end, if the phrase occurs in
$[\text{position}, v]$, it ends at $v$. The loop over lines 7–8 shrinks the interval to the
smallest size that still includes all terms in order. Lines 9–12 verify adjacency. On line
12 note that $u$ (and not $v$) is passed as the second argument to the recursive call; this
correctly handles the case in which two terms $t_i$ and $t_j$ are equal ($1 \le i < j \le n$).

**Worked trace** — `nextPhrase(“first witch”, −∞)`:

$$
\begin{aligned}
\mathrm{next}(\text{“first”}, -\infty) &= \mathrm{first}(\text{“first”}) = 2205 \\
\mathrm{next}(\text{“witch”}, 2205) &= 27555 \quad (\text{does not immediately follow}) \\
\mathrm{prev}(\text{“first”}, 27555) &= 26267 \quad (\text{skipped 15 occurrences of “first”}) \\
\mathrm{next}(\text{“first”}, 26267) &= 27673 \quad (\text{interval } [26267, 27555] \text{ has length } 1288 \ne 2)
\end{aligned}
$$

The calls to `prev` on line 8 are not strictly necessary but aid complexity analysis.

**Generating all occurrences** of a phrase requires an outer loop:

```
u ← −∞
while u < ∞ do
    [u, v] ← nextPhrase(“t1 t2 ... tn”, u)
    if u ≠ ∞ then
        report the interval [u, v]
```

Again $u$ (not $v$) is passed to `nextPhrase`, so the function correctly locates all
overlapping occurrences (e.g. all six occurrences of "spam spam spam" in "Spam spam spam
spam / Spam spam spam spam").

**Complexity.** Each call to `nextPhrase` makes $O(n)$ method calls ($n$ `next` calls
followed by $n-1$ `prev` calls). Each occurrence of a term $t_i$ can be included in at most
one of the intervals computed by lines 1–8. The time complexity is therefore determined by
the length of the **shortest** postings list among the phrase terms:

$$
l = \min_{1 \le i \le n} l_{t_i}. \tag{2.1}
$$

In the worst case the algorithm requires $O(n \cdot l)$ method calls to locate all
occurrences. $O(n \cdot l)$ counts method calls, not steps; the cost of each call depends on
the implementation (§3).

**Adaptive measure.** Consider the interval $[u, v]$ just before the test at line 9: it
contains all terms in order and contains no smaller such interval. Call an interval with
this property a **candidate phrase**. If $\kappa$ is the number of candidate phrases in the
collection, the number of method calls to locate all occurrences is $O(n \cdot \kappa)$.

---

## 3. Implementing Inverted Indices (§2.1.2)

For an in-memory, static collection, the postings list for term $t$ may be stored in a fixed
array $P_t[\,]$ of length $l_t$. Example for "witch" in Shakespeare:

```
   1        2            31        32       33       34            92
 1598    27555    ···   745407   745429   745451   745467   ···  1245276
```

`first` and `last` return $P_t[1]$ and $P_t[l_t]$ in constant time. Three implementations of
`next`/`prev` are given, with different complexity characteristics. Define the length of the
**longest** postings list among the query terms:

$$
L = \max_{1 \le i \le n} l_{t_i}. \tag{2.2}
$$

### 3.1 Binary search

```
next (t, current) ≡
1    if lt = 0 or Pt[lt] ≤ current then
2        return ∞
3    if Pt[1] > current then
4        return Pt[1]
5    return Pt[binarySearch(t, 1, lt, current)]

binarySearch (t, low, high, current) ≡
6    while high − low > 1 do
7        mid ← ⌊(low + high)/2⌋
8        if Pt[mid] ≤ current then
9            low ← mid
10       else
11           high ← mid
12   return high
```
*Figure 2.3 — `next` via binary search. `binarySearch` assumes $P_t[\text{low}] \le
\text{current}$ and $P_t[\text{high}] > \text{current}$; lines 1–4 establish this
precondition and lines 6–11 maintain it as an invariant. `prev` is similar.*

Each `next`/`prev` call costs $O(\log(l_t))$. The phrase-search complexity becomes
$O(n \cdot l \cdot \log(L))$, or $O(n \cdot \kappa \cdot \log(L))$ in terms of candidate
phrases. This is excellent when a phrase mixes frequent and infrequent terms, but wasteful
when terms have similar frequencies.

### 3.2 Linear scan (cached offset)

As the phrase-search algorithm makes successive `next` calls for a given term $t_i$, the
second arguments strictly increase across calls (including recursive calls); up to $l$ calls
may be made:

$$
\mathrm{next}(t_i, v_1), \mathrm{next}(t_i, v_2), \ldots, \mathrm{next}(t_i, v_l),
\quad v_1 < v_2 < \cdots < v_l,
$$

and the results also strictly increase:
$\mathrm{next}(t_i, v_1) < \mathrm{next}(t_i, v_2) < \cdots < \mathrm{next}(t_i, v_l)$.

This motivates caching the offset of the previously returned value and continuing the scan
from there.

```
next (t, current) ≡
1    if lt = 0 or Pt[lt] ≤ current then
2        return ∞
3    if Pt[1] > current then
4        ct ← 1
5        return Pt[ct]
6    if ct > 1 and Pt[ct − 1] > current then
7        ct ← 1
8    while Pt[ct] ≤ current do
9        ct ← ct + 1
10   return Pt[ct]
```
*Figure 2.4 — `next` via linear scan. $c_t$ caches the array offset of the last non-infinite
result returned for term $t$. The scan starts from the cached offset when possible; lines
6–7 reset it if the call's argument is not consistent with strictly increasing access.*

A separate cached value is kept per term (e.g. $c_{\text{first}}$ and $c_{\text{witch}}$).
With matching caching for `prev`, the phrase-search algorithm scans each postings list
accessing each element $O(1)$ times, giving overall time complexity $O(n \cdot L)$. Here the
adaptive nature provides no benefit; this is appropriate when all postings lists are about
the same length ($l \approx L$).

### 3.3 Galloping (exponential) search

A third implementation combines both: scan forward from a cached position in exponentially
increasing steps ("galloping") until the answer is passed, then binary-search the range
formed by the last two steps.

```
next (t, current) ≡
1    if lt = 0 or Pt[lt] ≤ current then
2        return ∞
3    if Pt[1] > current then
4        ct ← 1
5        return Pt[ct]
6    if ct > 1 and Pt[ct − 1] ≤ current then
7        low ← ct − 1
8    else
9        low ← 1
10   jump ← 1
11   high ← low + jump
12   while high < lt and Pt[high] ≤ current do
13       low ← high
14       jump ← 2 · jump
15       high ← low + jump
16   if high > lt then
17       high ← lt
18   ct ← binarySearch(t, low, high, current)
19   return Pt[ct]
```
*Figure 2.5 — `next` via galloping search. Lines 6–9 set an initial `low` with
$P_t[\text{low}] \le \text{current}$, using the cached value if possible. Lines 12–17 gallop
ahead in exponentially increasing steps until $P_t[\text{high}] > \text{current}$. The final
result is determined by `binarySearch` (Figure 2.3).*

*(Figure 2.6 in the book illustrates the access patterns of the three approaches for
`prev(“witch”, 745429) = 745407`: binary search uses 7 accesses, sequential scan 34,
galloping 12. Both scanning and galloping leave the cached offset at 31.)*

**Complexity of galloping search.** Let $c_t^{\,j}$ be the cached value after the $j$-th
`next` call for term $t$ during a phrase search, so that
$P_t[c_t^{\,1}] = \mathrm{next}(t, v_1), \ldots, P_t[c_t^{\,l}] = \mathrm{next}(t, v_l)$.
The work done by a call depends on the change $\Delta c$ in the cached value, and is
$O(\log(\Delta c))$. Define

$$
\Delta c_1 = c_t^{\,1}, \quad
\Delta c_2 = c_t^{\,2} - c_t^{\,1}, \quad \ldots, \quad
\Delta c_l = c_t^{\,l} - c_t^{\,l-1}.
$$

Then the total work done by `next` calls for term $t$ is

$$
\sum_{j=1}^{l} O(\log(\Delta c_j)) \;=\; O\!\left(\log\!\left(\prod_{j=1}^{l} \Delta c_j\right)\right). \tag{2.3}
$$

The arithmetic mean of a list of nonnegative numbers is always $\ge$ its geometric mean:

$$
\frac{\sum_{j=1}^{l} \Delta c_j}{l} \;\ge\; \sqrt[\,l\,]{\prod_{j=1}^{l} \Delta c_j}, \tag{2.4}
$$

and since $\sum_{j=1}^{l} \Delta c_j \le L$,

$$
\prod_{j=1}^{l} \Delta c_j \;\le\; (L/l)^{l}. \tag{2.5}
$$

Therefore the total work done by `next` (or `prev`) calls for term $t$ is

$$
O\!\left(\log\!\left(\prod_{j=1}^{l} \Delta c_j\right)\right)
\;\subseteq\; O\!\left(\log\!\left((L/l)^{l}\right)\right) \tag{2.6}
$$
$$
\;=\; O\!\left(l \cdot \log(L/l)\right). \tag{2.7}
$$

The overall time complexity for a phrase with $n$ terms is
$O(n \cdot l \cdot \log(L/l))$. When $l \ll L$ this resembles binary search; when
$l \approx L$ it resembles scanning. Accounting for the adaptive nature gives
$O(n \cdot \kappa \cdot \log(L/\kappa))$.

---

## 4. Documents and Other Elements (§2.1.3)

Most IR systems operate over a standard retrieval unit: the **document**. What constitutes a
document is application-dependent (an e-mail message, a Web page, a newspaper article, a
play, etc.). Using simple containment checks over the ADT methods, structural relationships
can be computed — e.g. to find the speech containing the phrase "first witch" first located
at $[745406, 745407]$:

$$
\mathrm{prev}(\text{“<SPEECH>”}, 745406) = 745404, \qquad
\mathrm{next}(\text{“</SPEECH>”}, 745404) = 745425,
$$

then confirm that $[745406, 745407]$ is contained in $[745404, 745425]$. The containment
check is necessary because the phrase may not always occur as part of a speech.

### 4.1 Document-oriented indices

Positions may be split into a **document number** and an **offset within the document**,
written with the notation $n{:}m$, where $n$ is a document identifier (docid) and $m$ is an
offset. The ADT methods still operate as before but accept and return docid:offset pairs.

**Worked values** (document-centric index over Shakespeare):

$$
\begin{aligned}
&\mathrm{first}(\text{“hurlyburly”}) = 9{:}30963 & &\mathrm{last}(\text{“thunder”}) = 37{:}12538 \\
&\mathrm{first}(\text{“witching”}) = 8{:}25805 & &\mathrm{last}(\text{“witching”}) = 8{:}25805 \\
&\mathrm{next}(\text{“witch”}, 22{:}288) = 22{:}310 & &\mathrm{prev}(\text{“witch”}, 22{:}310) = 22{:}288 \\
&\mathrm{next}(\text{“hurlyburly”}, 9{:}30963) = 22{:}293 & &\mathrm{prev}(\text{“hurlyburly”}, 22{:}293) = 9{:}30963 \\
&\mathrm{next}(\text{“witch”}, 37{:}10675) = \infty & &\mathrm{prev}(\text{“witch”}, 1{:}1598) = -\infty
\end{aligned}
$$

Offsets within a document start at 1 and range up to the document length. $-\infty$ and
$\infty$ are still used as file markers ($-\infty$ read as $-\infty{:}{-\infty}$ and $\infty$
as $\infty{:}\infty$). Positions are compared with the document number as primary key:

$$
n{:}m < n'{:}m' \iff \bigl(n < n' \;\text{or}\; (n = n' \;\text{and}\; m < m')\bigr).
$$

An index optimized this way is a **schema-dependent inverted index** (the division of text
into retrieval units — its schema — is fixed at index-construction time). An index without
these optimizations is a **schema-independent inverted index**, which allows the definition
of a document to be specified at query time, at a possible cost in execution time.

### 4.2 Document-oriented statistics

| Symbol | Name | Meaning |
|---|---|---|
| $N_t$ | document frequency | number of documents in the collection containing term $t$ |
| $f_{t,d}$ | term frequency | number of times term $t$ appears in document $d$ |
| $l_d$ | document length | measured in tokens |
| $l_{avg}$ | average length | average document length across the collection |
| $N$ | document count | total number of documents in the collection |

with

$$
\sum_{d \in \mathcal{C}} l_d = \sum_{t \in V} l_t = l_{\mathcal{C}}, \qquad l_{avg} = l_{\mathcal{C}} / N.
$$

(Over Shakespeare's plays, $l_{avg} = 34363$; for $t = \text{“witch”}$ and $d = 22$
(Macbeth), $N_t = 18$, $f_{t,d} = 52$, $l_d = 26805$.)

### 4.3 Document-oriented ADT methods

To break a position into its parts:

- `docid(position)` — returns the docid associated with a position.
- `offset(position)` — returns the within-document offset associated with a position.

When a posting takes the form $u{:}v$, these return $u$ and $v$ respectively.

Document-oriented versions of the basic methods (used by Boolean retrieval, §6):

- `firstDoc(t)` — returns the docid of the first document containing term $t$.
- `lastDoc(t)` — returns the docid of the last document containing term $t$.
- `nextDoc(t, current)` — returns the docid of the first document **after** `current` that contains term $t$.
- `prevDoc(t, current)` — returns the docid of the last document **before** `current` that contains term $t$.

In a schema-dependent index, postings sharing a common docid prefix can be separated to
produce postings of the form

$$
(d,\; f_{t,d},\; \langle p_1, \ldots, p_{f_{t,d}}\rangle)
$$

where $\langle p_1, \ldots, p_{f_{t,d}}\rangle$ lists the offsets of all $f_{t,d}$ occurrences
of $t$ within document $d$. For example, the postings list for "witch":

$$
(1, 3, \langle 1598, 27555, 31463\rangle), \ldots, (22, 52, \langle 266, 288, \ldots\rangle), \ldots, (37, 1, \langle 10675\rangle).
$$

### 4.4 Four index types

- **docid index** — for each term, just the document identifiers of all documents containing
  it. Sufficient for filtering with basic Boolean queries (§6) and for *coordination level
  ranking*.
- **frequency index** — postings of the form $(d, f_{t,d})$. Sufficient for many effective
  ranking methods (e.g. the vector space model), but insufficient for phrase searching and
  advanced filtering.
- **positional index** — postings of the form
  $(d, f_{t,d}, \langle p_1, \ldots, p_{f_{t,d}}\rangle)$. Supports everything a frequency
  index does, plus phrase queries, proximity ranking (§5), and other position-aware and
  structural queries.
- **schema-independent index** — lacks the document-oriented optimizations of a positional
  index, but otherwise the two may be used interchangeably.

The first three are schema-dependent.

---

## 5. Running Example (Tables 2.1, 2.2, 2.4)

### Table 2.1 — Text fragment from Shakespeare's *Romeo and Juliet*, act I, scene 1

Each line is treated as a document (tags omitted to shorten the example).

| Document ID | Document Content |
|---|---|
| 1 | Do you quarrel, sir? |
| 2 | Quarrel sir! no, sir! |
| 3 | If you do, sir, I am for you: I serve as good a man as you. |
| 4 | No better. |
| 5 | Well, sir. |

### Table 2.2 — Postings lists for the terms in Table 2.1

In each case the **length of the list is appended to the start** of the actual list (the
number before the semicolon). Positional postings are $(d, f_{t,d}, \langle \text{offsets}\rangle)$.

| Term | Docid List | Positional List | Schema-Independent |
|---|---|---|---|
| a | 1; 3 | 1; $(3, 1, \langle 13\rangle)$ | 1; 21 |
| am | 1; 3 | 1; $(3, 1, \langle 6\rangle)$ | 1; 14 |
| as | 1; 3 | 1; $(3, 2, \langle 11, 15\rangle)$ | 2; 19, 23 |
| better | 1; 4 | 1; $(4, 1, \langle 2\rangle)$ | 1; 26 |
| do | 2; 1, 3 | 2; $(1, 1, \langle 1\rangle), (3, 1, \langle 3\rangle)$ | 2; 1, 11 |
| for | 1; 3 | 1; $(3, 1, \langle 7\rangle)$ | 1; 15 |
| good | 1; 3 | 1; $(3, 1, \langle 12\rangle)$ | 1; 20 |
| i | 1; 3 | 1; $(3, 2, \langle 5, 9\rangle)$ | 2; 13, 17 |
| if | 1; 3 | 1; $(3, 1, \langle 1\rangle)$ | 1; 9 |
| man | 1; 3 | 1; $(3, 1, \langle 14\rangle)$ | 1; 22 |
| no | 2; 2, 4 | 2; $(2, 1, \langle 3\rangle), (4, 1, \langle 1\rangle)$ | 2; 7, 25 |
| quarrel | 2; 1, 2 | 2; $(1, 1, \langle 3\rangle), (2, 1, \langle 1\rangle)$ | 2; 3, 5 |
| serve | 1; 3 | 1; $(3, 1, \langle 10\rangle)$ | 1; 18 |
| sir | 4; 1, 2, 3, 5 | 4; $(1, 1, \langle 4\rangle), (2, 2, \langle 2, 4\rangle), (3, 1, \langle 4\rangle), (5, 1, \langle 2\rangle)$ | 5; 4, 6, 8, 12, 28 |
| well | 1; 5 | 1; $(5, 1, \langle 1\rangle)$ | 1; 27 |
| you | 2; 1, 3 | 2; $(1, 1, \langle 2\rangle), (3, 3, \langle 2, 8, 16\rangle)$ | 4; 2, 10, 16, 24 |

### Table 2.4 — Summary of notation for inverted indices

**Basic inverted index methods**
- `first(term)` — returns the first position at which the term occurs.
- `last(term)` — returns the last position at which the term occurs.
- `next(term, current)` — returns the next position at which the term occurs after `current`.
- `prev(term, current)` — returns the previous position at which the term occurs before `current`.

**Document-oriented equivalents of the basic methods**
- `firstDoc(term)`, `lastDoc(term)`, `nextDoc(term, current)`, `prevDoc(term, current)`.

**Schema-dependent index positions**
- $n{:}m$ — $n$ = docid and $m$ = offset.
- `docid(position)` — returns the docid associated with a position.
- `offset(position)` — returns the within-document offset associated with a position.

**Symbols for document and term statistics**
- $l_t$ — the length of $t$'s postings list.
- $N_t$ — the number of documents containing $t$.
- $f_{t,d}$ — the number of occurrences of $t$ within the document $d$.
- $l_d$ — length of the document $d$, in tokens.
- $l_{avg}$ — the average document length in the collection.
- $N$ — the total number of documents in the collection.

**The structure of postings lists**
- docid index: $d_1, d_2, \ldots, d_{N_t}$
- frequency index: $(d_1, f_{t,d_1}), (d_2, f_{t,d_2}), \ldots$
- positional index: $(d_1, f_{t,d_1}, \langle p_1, \ldots, p_{f_{t,d_1}}\rangle), \ldots$
- schema-independent: $p_1, p_2, \ldots, p_{l_t}$

---

## 6. Retrieval and Ranking — query model (§2.2 intro)

Queries for ranked retrieval are expressed as **term vectors**, written explicitly as
$\langle t_1, t_2, \ldots, t_n\rangle$. For example the query `william shakespeare marriage`
is written $\langle\text{“william”}, \text{“shakespeare”}, \text{“marriage”}\rangle$.

Queries are represented as **vectors (lists)** rather than sets because terms may be repeated
and term ordering may be significant. In ranking formulae, $q_t$ denotes the number of times
term $t$ appears in the query.

**Boolean predicates** are composed with the standard Boolean operators (AND, OR, NOT). The
result of a Boolean query is a **set** of documents matching the predicate. For example:

```
“william” AND “shakespeare” AND NOT (“marlowe” OR “bacon”)
```

specifies those documents containing "william" and "shakespeare" but not containing either
"marlowe" or "bacon".

**Key interpretive difference.** Boolean predicates are usually interpreted as **strict
filters** — a document not matching the predicate is not returned. Term vectors are usually
interpreted as **summarizing an information need** — not all terms need appear in a document
for it to be returned; it is the ranked-retrieval method's role to determine the impact of
missing terms.

Boolean and ranked retrieval combine naturally into a **two-step process**: a Boolean
predicate first restricts retrieval to a subset of the collection, and the resulting
subcollection is then ranked with respect to the topic.

---

## 7. Proximity Ranking — Cover Density Ranking (§2.2.2)

This method explicitly depends **only on term proximity**. Term frequency is handled
implicitly; document frequency, document length, and other features play no role at all.

### 7.1 Covers

> When the components of a term vector $\langle t_1, t_2, \ldots, t_n\rangle$ appear in close
> proximity within a document, it suggests the document is more likely to be relevant than
> one in which the terms appear farther apart.

**Definition (cover).** Given a term vector $\langle t_1, t_2, \ldots, t_n\rangle$, a
**cover** for the vector is an interval in the collection $[u, v]$ that contains a match to
all the terms **without containing a smaller interval** $[u', v']$, $u \le u' \le v' \le v$,
that also contains a match to all the terms.

The candidate phrases of §2 are a special case of a cover in which all terms appear in order.

**Examples** (collection of Table 2.1):

- Covers for $\langle\text{“you”}, \text{“sir”}\rangle$: $[1{:}2, 1{:}4]$, $[3{:}2, 3{:}4]$,
  and $[3{:}4, 3{:}8]$. The interval $[3{:}4, 3{:}16]$ is **not** a cover (even though both
  terms are contained within it) because it contains the cover $[3{:}4, 3{:}8]$.
- Covers for $\langle\text{“quarrel”}, \text{“sir”}\rangle$: $[1{:}3, 1{:}4]$ and
  $[2{:}1, 2{:}2]$.

Covers may overlap. However, a token matching a term $t_i$ appears in at most $n \cdot l$
covers, where $l$ is the length of the shortest postings list for the terms in the vector. A
new cover starts at each occurrence of a term from the vector, so the total number of covers
is constrained by $n \cdot l$ and does **not** depend on the length $L$ of the longest
postings list. Define $\kappa$ to be the number of covers for a term vector occurring in a
document collection, where $\kappa \le n \cdot l$.

### 7.2 Finding covers

The cover-finding algorithm is a close cousin of the phrase-search algorithm (Figure 2.2).

```
nextCover (⟨t1, ..., tn⟩, position) ≡
1    v ← max 1≤i≤n (next(ti, position))
2    if v = ∞ then
3        return [∞, ∞]
4    u ← min 1≤i≤n (prev(ti, v + 1))
5    if docid(u) = docid(v) then
6        return [u, v]
7    else
8        return nextCover(⟨t1, ..., tn⟩, u)
```
*Figure 2.10 — Locates the next occurrence of a cover for the term vector
$\langle t_1, \ldots, t_n\rangle$ after a given position.*

- Line 1 determines the smallest position $v$ such that $[\text{position}, v]$ contains all
  the terms in the vector; a cover starting after $u$ cannot end before this position.
- Line 4 shrinks the interval ending at $v$, adjusting $u$ so that no smaller interval ending
  at $v$ contains all the terms.
- Line 5 checks whether $u$ and $v$ are contained in the same document; if not, `nextCover`
  is called recursively.

The same-document check (line 5) is required only because the cover will contribute to a
document's score. Technically $[1{:}4, 2{:}1]$ is an acceptable cover for
$\langle\text{“quarrel”}, \text{“sir”}\rangle$, but in a schema-dependent index a cover that
crosses document boundaries is unlikely to be meaningful.

### 7.3 Scoring

Ranking is based on two assumptions:

1. the **shorter** the cover, the more likely the text containing it is relevant;
2. the **more covers** contained in a document, the more likely the document is relevant.

The first assumption suggests scoring an individual cover by its length; the second suggests
summing the individual cover scores for a document. Combining these, a document $d$
containing covers $[u_1, v_1], [u_2, v_2], [u_3, v_3], \ldots$ is scored by:

$$
\mathrm{score}(d) \;=\; \sum_{i} \left( \frac{1}{v_i - u_i + 1} \right). \tag{2.15}
$$

### 7.4 Query processing

```
rankProximity (⟨t1, ..., tn⟩, k) ≡
1    [u, v] ← nextCover(⟨t0, t1, ..., tn⟩, −∞)
2    d ← docid(u)
3    score ← 0
4    j ← 0
5    while u < ∞ do
6        if d < docid(u) then
7            j ← j + 1
8            Result[j].docid ← d
9            Result[j].score ← score
10           d ← docid(u)
11           score ← 0
12       score ← score + 1/(v − u + 1)
13       [u, v] ← nextCover(⟨t1, ..., tn⟩, u)
14   if d < ∞ then
15       j ← j + 1
16       Result[j].docid ← d
17       Result[j].score ← score
18   sort Result[1..j] by score
19   return Result[1..k]
```
*Figure 2.11 — Query processing for proximity ranking. `nextCover` (Figure 2.10) is called
to generate each cover. (Transcribed verbatim, including the `⟨t0, t1, ..., tn⟩` argument on
line 1 as printed in the source.)*

Covers are generated by calls to `nextCover` and processed one by one in the while loop
(lines 5–13). The number of covers $\kappa$ in the collection is exactly the number of
`nextCover` calls at line 13. When a document boundary is crossed (line 6), the score and
docid are stored in the `Result` array (lines 8–9). After all covers are processed, the last
document is recorded (lines 14–17), the array is sorted by score (line 18), and the top $k$
documents are returned (line 19).

### 7.5 Complexity

As `rankProximity` calls `nextCover`, the position passed as its second argument strictly
increases; in turn the second arguments to `next` and `prev` strictly increase, so `next`
and `prev` may be implemented with galloping search. When galloping search is used, the
overall time complexity of `rankProximity` is

$$
O\!\left(n^2\, l \cdot \log(L/l)\right).
$$

The complexity is quadratic in $n$ because there may be $O(n \cdot l)$ covers in the worst
case. Accounting for the adaptive nature gives

$$
O\!\left(n \cdot \kappa \cdot \log(L/\kappa)\right).
$$

### 7.6 Behavior and worked scores

For a document to receive a nonzero score, **all** terms must be present in it (proximity
ranking shares the behavior, until recently, of many commercial search engines).

Applied to the collection of Table 2.1:

- Query $\langle\text{“you”}, \text{“sir”}\rangle$: score $0.33$ to document 1, $0.53$ to
  document 3, $0$ to the remaining documents.
- Query $\langle\text{“quarrel”}, \text{“sir”}\rangle$: score $0.50$ to documents 1 and 2,
  $0.00$ to documents 3 to 5.

Unlike cosine similarity, the second occurrence of "sir" in document 2 does not contribute to
the document's score: the frequency of individual terms is not a factor — rather the
frequency and proximity of their co-occurrence are. A document could include many matches to
all terms but contain only a single cover, with the query terms clustered into discrete
groups.

---

## 8. Boolean Retrieval (§2.2.3)

Explicit support for Boolean queries is important in application areas such as digital
libraries and the legal domain. In contrast to ranked retrieval, Boolean retrieval returns
**sets** of documents rather than ranked lists. Under the Boolean retrieval model, a term $t$
specifies the set of documents containing it. The standard operators:

| Query | Meaning |
|---|---|
| $A$ AND $B$ | intersection of $A$ and $B$ ($A \cap B$) |
| $A$ OR $B$ | union of $A$ and $B$ ($A \cup B$) |
| NOT $A$ | complement of $A$ with respect to the document collection ($\bar{A}$) |

where $A$ and $B$ are terms or other Boolean queries.

**Examples** (collection of Table 2.1):

- $(\text{“quarrel”}\text{ OR }\text{“sir”})\text{ AND }\text{“you”}$ specifies the set $\{1, 3\}$.
- $(\text{“quarrel”}\text{ OR }\text{“sir”})\text{ AND NOT }\text{“you”}$ specifies the set $\{2, 5\}$.

### 8.1 Candidate solutions

The algorithm is another variant of the phrase-search algorithm (Figure 2.2) and the
cover-finding algorithm (Figure 2.10). It locates **candidate solutions**: a candidate
solution represents a **range of documents** that together satisfy the Boolean query, such
that no smaller range of documents contained within it also satisfies the query. When the
range represented by a candidate solution has **length 1**, that single document satisfies
the query and should be included in the result set.

### 8.2 docRight / docLeft

Two functions extend `nextDoc` and `prevDoc` over Boolean queries:

- `docRight(Q, u)` — end point of the first candidate solution to $Q$ starting after document $u$.
- `docLeft(Q, v)` — start point of the last candidate solution to $Q$ ending before document $v$.

For terms:

$$
\mathrm{docRight}(t, u) \equiv \mathrm{nextDoc}(t, u), \qquad
\mathrm{docLeft}(t, v) \equiv \mathrm{prevDoc}(t, v).
$$

For the AND and OR operators:

$$
\begin{aligned}
\mathrm{docRight}(A \text{ AND } B, u) &\equiv \max(\mathrm{docRight}(A, u),\, \mathrm{docRight}(B, u)) \\
\mathrm{docLeft}(A \text{ AND } B, v) &\equiv \min(\mathrm{docLeft}(A, v),\, \mathrm{docLeft}(B, v)) \\
\mathrm{docRight}(A \text{ OR } B, u) &\equiv \min(\mathrm{docRight}(A, u),\, \mathrm{docRight}(B, u)) \\
\mathrm{docLeft}(A \text{ OR } B, v) &\equiv \max(\mathrm{docLeft}(A, v),\, \mathrm{docLeft}(B, v))
\end{aligned}
$$

These definitions are applied recursively. **Worked examples:**

$$
\begin{aligned}
\mathrm{docRight}((\text{“quarrel”}\text{ OR }\text{“sir”})\text{ AND }\text{“you”}, 1)
&\equiv \max(\mathrm{docRight}(\text{“quarrel”}\text{ OR }\text{“sir”}, 1),\, \mathrm{docRight}(\text{“you”}, 1)) \\
&\equiv \max(\min(\mathrm{docRight}(\text{“quarrel”}, 1), \mathrm{docRight}(\text{“sir”}, 1)),\, \mathrm{nextDoc}(\text{“you”}, 1)) \\
&\equiv \max(\min(\mathrm{nextDoc}(\text{“quarrel”}, 1), \mathrm{nextDoc}(\text{“sir”}, 1)),\, 3) \\
&\equiv \max(\min(2, 2),\, 3) \\
&\equiv 3
\end{aligned}
$$

$$
\begin{aligned}
\mathrm{docLeft}((\text{“quarrel”}\text{ OR }\text{“sir”})\text{ AND }\text{“you”}, 4)
&\equiv \min(\mathrm{docLeft}(\text{“quarrel”}\text{ OR }\text{“sir”}, 4),\, \mathrm{docLeft}(\text{“you”}, 4)) \\
&\equiv \min(\max(\mathrm{docLeft}(\text{“quarrel”}, 4), \mathrm{docLeft}(\text{“sir”}, 4)),\, \mathrm{prevDoc}(\text{“you”}, 4)) \\
&\equiv \min(\max(\mathrm{prevDoc}(\text{“quarrel”}, 4), \mathrm{prevDoc}(\text{“sir”}, 4)),\, 3) \\
&\equiv \min(\max(2, 3),\, 3) \\
&\equiv 3
\end{aligned}
$$

(Definitions for NOT are deferred to §8.4.)

### 8.3 nextSolution and generating all solutions

```
nextSolution (Q, position) ≡
1    v ← docRight(Q, position)
2    if v = ∞ then
3        return ∞
4    u ← docLeft(Q, v + 1)
5    if u = v then
6        return u
7    else
8        return nextSolution(Q, v)
```
*Figure 2.12 — Locates the next solution to the Boolean query $Q$ after a given position.
`nextSolution` calls `docRight` and `docLeft` to generate a candidate solution; these make
recursive calls that depend on the structure of the query.*

Just after line 4, the interval $[u, v]$ contains the candidate solution. If it consists of a
single document ($u = v$), it is returned; otherwise the function recurses. Given this
function, all solutions to a Boolean query $Q$ are generated by:

```
u ← −∞
while u < ∞ do
    u ← nextSolution(Q, u)
    if u < ∞ then
        report docid(u)
```

**Complexity.** Using a galloping-search implementation of `nextDoc` and `prevDoc`, the time
complexity is $O(n \cdot l \cdot \log(L/l))$, where $n$ is the number of terms in the query.
If a docid or frequency index is used (no positional information), $l$ and $L$ are the
lengths of the shortest and longest postings lists of the query terms measured in number of
documents. In terms of the number of candidate solutions $\kappa$ (the adaptive measure), the
complexity becomes $O(n \cdot \kappa \cdot \log(L/\kappa))$. The `docLeft` call on line 4 can
be avoided, but it provides a clear definition of a candidate solution for the analysis.

### 8.4 The NOT operator

Defining `docRight`/`docLeft` for NOT directly is problematic. Instead, **De Morgan's laws**
transform a query, moving NOT operators inward until they are directly associated with query
terms:

$$
\mathrm{NOT}(A \text{ AND } B) \equiv \mathrm{NOT}\,A \text{ OR } \mathrm{NOT}\,B, \qquad
\mathrm{NOT}(A \text{ OR } B) \equiv \mathrm{NOT}\,A \text{ AND } \mathrm{NOT}\,B.
$$

For example,

```
“william” AND “shakespeare” AND NOT (“marlowe” OR “bacon”)
```

is transformed into

```
“william” AND “shakespeare” AND (NOT “marlowe” AND NOT “bacon”).
```

This does not change the number of AND/OR operators, and hence does not change $n$. After
applying De Morgan's laws, the query contains expressions of the form $\mathrm{NOT}\,t$ where
$t$ is a term. These require corresponding `docRight`/`docLeft` definitions, which can be
written in terms of `nextDoc` and `prevDoc`:

```
docRight (NOT t, u) ≡
    u′ ← nextDoc(t, u)
    while u′ = u + 1 do
        u ← u′
        u′ ← nextDoc(t, u)
    return u + 1
```

**Caveat.** This approach performs acceptably when few documents contain $t$, but may perform
unacceptably when most documents contain $t$ — essentially reverting to a linear scan and
losing the benefit of galloping search. Moreover, the equivalent `docLeft(NOT t, v)` requires
a backward scan, violating the requirement to realize galloping search's benefits. Instead,
the NOT operator may be implemented directly over the index data structures by extending the
index with explicit `nextDoc(NOT t, u)` and `prevDoc(NOT t, v)` methods.

---

## 9. Implementation dependency map (quick reference)

- **Cover density / proximity ranking** (`rankProximity`, Fig 2.11) depends on:
  `nextCover` (Fig 2.10) → `next`, `prev`, `docid`; scoring formula (2.15); galloping `next`/`prev` (Fig 2.5) for the stated complexity.
- **`nextCover`** (Fig 2.10) depends on: `next`, `prev` (ADT, §1; implementations §3), `docid` (§4.3).
- **Boolean retrieval** (`nextSolution`, Fig 2.12) depends on:
  `docRight`/`docLeft` (§8.2) → `nextDoc`, `prevDoc` (§4.3), `max`/`min`; `docid` (§4.3);
  De Morgan transform + `docRight(NOT t, ·)` (§8.4) for NOT.
- **Both** are structural variants of `nextPhrase` (Fig 2.2, §2).
- A **docid index** suffices for Boolean retrieval; a **positional or schema-independent
  index** is required for cover-based proximity ranking (covers need offsets within documents).
