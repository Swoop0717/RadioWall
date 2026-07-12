"""GestureDetector timing semantics with synthetic edge streams."""

from radiowall.input.gestures import DOUBLE_S, LONG_S, Gesture, GestureDetector


def run(script):
    """script: list of (now, edges) steps → flat list of gestures."""
    det = GestureDetector()
    out = []
    for now, edges in script:
        out.extend(det.update(edges, now))
    return out


def test_short_press():
    out = run([
        (0.00, [(0.00, True)]),
        (0.10, [(0.10, False)]),
        (0.15, []),                       # inside double window: nothing yet
        (0.10 + DOUBLE_S + 0.05, []),     # window closed
    ])
    assert out == [Gesture.SHORT]


def test_short_not_emitted_early():
    det = GestureDetector()
    det.update([(0.0, True), (0.1, False)], 0.1)
    assert det.update([], 0.1 + DOUBLE_S - 0.01) == []
    assert det.update([], 0.1 + DOUBLE_S + 0.01) == [Gesture.SHORT]


def test_double_press():
    out = run([
        (0.00, [(0.00, True)]),
        (0.10, [(0.10, False)]),
        (0.25, [(0.25, True)]),           # second down 0.15s after release
        (0.35, [(0.35, False)]),
        (1.00, []),
    ])
    assert out == [Gesture.DOUBLE]        # and nothing else afterwards


def test_two_slow_presses_are_two_shorts():
    gap = DOUBLE_S + 0.2
    t2 = 0.1 + gap
    out = run([
        (0.00, [(0.00, True), (0.10, False)]),
        (t2, [(t2, True)]),
        (t2 + 0.1, [(t2 + 0.1, False)]),
        (t2 + 0.1 + DOUBLE_S + 0.05, []),
    ])
    assert out == [Gesture.SHORT, Gesture.SHORT]


def test_long_fires_while_held():
    det = GestureDetector()
    assert det.update([(0.0, True)], 0.0) == []
    assert det.update([], LONG_S - 0.05) == []
    assert det.update([], LONG_S + 0.05) == [Gesture.LONG]


def test_long_release_swallowed():
    det = GestureDetector()
    det.update([(0.0, True)], 0.0)
    assert det.update([], LONG_S + 0.05) == [Gesture.LONG]
    # release after the LONG: no SHORT, no anything
    assert det.update([(LONG_S + 0.5, False)], LONG_S + 0.5) == []
    assert det.update([], LONG_S + 2.0) == []


def test_long_only_fires_once_per_hold():
    det = GestureDetector()
    det.update([(0.0, True)], 0.0)
    assert det.update([], LONG_S + 0.1) == [Gesture.LONG]
    assert det.update([], LONG_S + 5.0) == []


def test_rapid_triple_press():
    # press1 + press2 = DOUBLE; press3 starts fresh → SHORT after window
    out = run([
        (0.00, [(0.00, True), (0.05, False),
                (0.10, True), (0.15, False),
                (0.20, True), (0.25, False)]),
        (0.25 + DOUBLE_S + 0.05, []),
    ])
    assert out == [Gesture.DOUBLE, Gesture.SHORT]


def test_short_then_long():
    long_start = DOUBLE_S + 0.5
    det = GestureDetector()
    det.update([(0.0, True), (0.1, False)], 0.1)
    out1 = det.update([], 0.1 + DOUBLE_S + 0.05)
    out2 = det.update([(long_start, True)], long_start)
    out3 = det.update([], long_start + LONG_S + 0.05)
    assert (out1, out2, out3) == ([Gesture.SHORT], [], [Gesture.LONG])
