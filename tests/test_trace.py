from aurasenior import store, trace


def test_labels_for_flagged_items():
    items = [
        {"at": "2026-10-12T03:30:00+00:00", "step": "send", "channel": "whatsapp", "simulated": True},
        {"at": "2026-10-12T03:31:00+00:00", "step": "converse", "model": "scripted", "simulated": True},
        {"at": "2026-10-12T03:32:00+00:00", "step": "signal", "simulated_baseline": True, "simulated": True},
        {"at": "2026-10-12T03:33:00+00:00", "step": "send", "channel": "email", "simulated": False},
    ]
    lines = trace.format_trace(items).splitlines()
    assert "[SIMULATED]" in lines[0]
    assert "[SCRIPTED MODEL]" in lines[1] and "[SIMULATED]" not in lines[1]
    assert "[SIMULATED BASELINE]" in lines[2]
    assert "[" not in lines[3]


def test_masked_inputs_stay_masked(table, frozen, capsys):
    store.trace("hh1", "send", to="+12025550101", channel="rcs", simulated=True)
    trace.main(["hh1", "--since", "1h"])
    out = capsys.readouterr().out
    assert "0101" in out and "2025550" not in out and "[SIMULATED]" in out
