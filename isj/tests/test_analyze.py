"""isj analyze CLI tests (TASK-41): the topics-TSV parser.

The end-to-end analyze flow needs a live vLLM Analyst, so it is exercised by hand; here we pin
the pure parsing contract (2-col TSV, skip blanks/short rows, preserve tabs in the question).
"""

from isj_agent.analyze import read_topics


def test_read_topics_parses_two_columns(tmp_path):
    tsv = tmp_path / "topics.tsv"
    tsv.write_text("14\tWhat is X?\n15\tWhy Y?\n", encoding="utf-8")
    assert read_topics(tsv) == [("14", "What is X?"), ("15", "Why Y?")]


def test_read_topics_skips_blank_and_short_rows(tmp_path):
    tsv = tmp_path / "topics.tsv"
    tsv.write_text("14\tgood\n\n   \nheader_only\n\t\n15\talso good\n", encoding="utf-8")
    assert read_topics(tsv) == [("14", "good"), ("15", "also good")]


def test_read_topics_strips_the_id_but_keeps_the_question(tmp_path):
    tsv = tmp_path / "topics.tsv"
    tsv.write_text("  7  \t  a padded question  \n", encoding="utf-8")
    assert read_topics(tsv) == [("7", "  a padded question  ")]
