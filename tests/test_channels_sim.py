from aurasenior import channels, sim
from aurasenior.channels.base import OutboundMessage


def test_sim_send_writes_one_labelled_line_per_message():
    channels.reset()
    wa = channels.get("whatsapp")
    r = wa.send(OutboundMessage(person_id="p1", to="+910000000001", kind="voice", text="hello"))
    assert r.ok and r.simulated and r.provider_id.startswith("sim-")
    channels.get("email").send(OutboundMessage(person_id="p2", to="a@example.com", kind="email_template",
                                               template="aurasenior-update"))
    lines = sim.read("whatsapp")
    assert len(lines) == 1 and lines[0]["simulated"] is True and lines[0]["text"] == "hello"
    assert len(sim.read("email")) == 1


def test_every_channel_has_a_simulator():
    channels.reset()
    for ch in ("whatsapp", "rcs", "sms", "email"):
        a = channels.get(ch)
        assert a.simulated and a.channel == ch
