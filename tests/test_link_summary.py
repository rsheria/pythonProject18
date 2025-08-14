from utils.link_summary import LinkCheckSummary


def test_summary_counts_and_message():
    s = LinkCheckSummary()
    s.update(0, 'ONLINE', replaced=True)
    s.update(1, 'OFFLINE')
    s.update(2, 'UNKNOWN')
    assert s.counts['ONLINE'] == 1
    assert s.counts['OFFLINE'] == 1
    assert s.counts['UNKNOWN'] == 1
    msg = s.message()
    assert 'Link check finished' in msg
    assert '3 rows' in msg
    assert 'replaced 1' in msg
    assert 'ONLINE 1' in msg and 'OFFLINE 1' in msg and 'UNKNOWN 1' in msg


def test_summary_cancelled():
    s = LinkCheckSummary()
    s.update(0, 'ONLINE')
    s.update(1, 'OFFLINE', replaced=True)
    msg = s.message(cancelled=True)
    assert msg.startswith('Link check cancelled')
    assert '2 rows' in msg
    assert 'replaced 1' in msg