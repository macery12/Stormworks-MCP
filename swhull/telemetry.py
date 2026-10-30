"""Engine telemetry for in-game measurement: a microcontroller that steps the throttle and sends
readings to tools/telemetry_logger.py over the game's local HTTP (async.httpGet, localhost only).

The game's own docs (strings in the executable) give the API: async.httpGet(port, request_body)
and the callback httpReply(port, request_body, response_body). The microcontroller layout copies
the player's saved controllers: number inputs packed by a Composite Write block into the Lua
block, and the Lua block's composite output split by Composite Read blocks into the outputs.
"""
from xml.sax.saxutils import escape

PORT = 38480
STEPS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
HOLD_SECONDS = 40

# Microcontroller ports: (label, type, mode, x, z). Type 1 is a number, 0 on/off; mode 1 is an input.
NODES = (("Engine RPS", 1, 1, 0, 0), ("Fuel tank content", 1, 1, 1, 0), ("Engine temperature", 1, 1, 2, 0),
         ("Linear speed", 1, 1, 0, 1), ("Throttle", 1, 0, 1, 1), ("Starter", 0, 0, 2, 1))
WIDTH, LENGTH = 3, 2

# No comments and a statement per line, so the script survives if a parser folds the newlines.
LUA = """RUN = "{run}"
PORT = {port}
STEPS = {{{steps}}}
HOLD = {hold}
clock, tick, step, phase = 0, 0, 0, "start"
throttle, starter = 0, false
function onTick()
local rps, fuel, temp, speed = input.getNumber(1), input.getNumber(2), input.getNumber(3), input.getNumber(4)
clock, tick = clock + 1, tick + 1
if phase == "start" then
throttle = STEPS[1]
starter = rps < 4
if rps >= 4 and tick > 120 then phase, step, tick = "run", 1, 0 end
if phase == "start" and tick > 1200 then phase = "stalled" end
elseif phase == "run" then
throttle = STEPS[step]
starter = rps < 1
if tick >= HOLD then
step, tick = step + 1, 0
if step > #STEPS then phase, step, throttle = "done", #STEPS, 0 end
end
else
throttle, starter = 0, false
end
if clock % 60 == 0 then
async.httpGet(PORT, string.format("/log?run=%s&phase=%s&step=%d&s=%d&throttle=%.3f&rps=%.4f&fuel=%.4f&temp=%.3f&speed=%.4f", RUN, phase, step, clock // 60, throttle, rps, fuel, temp, speed))
end
output.setNumber(1, throttle)
output.setBool(1, starter)
end
function httpReply(port, request, response)
end
"""


def script(run, port=PORT, steps=STEPS, hold_seconds=HOLD_SECONDS):
    """The Lua sweep: start the engine, hold each throttle step, send one reading a second."""
    if not run.replace("_", "").replace("-", "").isalnum():
        raise ValueError("run name: letters, digits, - and _ only")
    return LUA.format(run=run, port=int(port), steps=",".join(f"{s:g}" for s in steps), hold=int(hold_seconds * 60))


def _position(x, z):
    attrs = (f' x="{x}"' if x else "") + (f' z="{z}"' if z else "")
    return f"<position{attrs}/>" if attrs else ""


def definition_xml(run, **options):
    """<microprocessor_definition> for the telemetry controller (ports listed in NODES)."""
    nodes = "".join(
        f'<n id="{i}" component_id="{i}"><node label="{label}"'
        + (f' mode="{mode}"' if mode else "") + (f' type="{typ}"' if typ else "") + ">"
        + _position(x, z) + "</node></n>"
        for i, (label, typ, mode, x, z) in enumerate(NODES, 1))
    lua = escape(script(run, **options), {'"': "&quot;"})
    inner = (
        '<c type="40"><object id="7" count="4"><pos x="-1.5"/>'
        + "".join(f'<in{i} component_id="{i}"/>' for i in range(1, 5)) + "</object></c>"
        f'<c type="56"><object id="8" script="{lua}"><pos/><in1 component_id="7"/></object></c>'
        '<c type="31"><object id="9"><pos x="1.5" y="0.5"/><in1 component_id="8"/></object></c>'
        '<c type="29"><object id="10"><pos x="1.5" y="-0.5"/><in1 component_id="8"/></object></c>')
    bridge = ("".join(f'<c type="2"><object id="{i}"><pos x="-3" y="{1.5 - i}"/></object></c>' for i in range(1, 5))
              + '<c type="3"><object id="5"><pos x="3" y="0.5"/><in1 component_id="9"/></object></c>'
              '<c type="1"><object id="6"><pos x="3" y="-0.5"/><in1 component_id="10"/></object></c>')
    return (f'<microprocessor_definition name="Engine telemetry {run}" description="Steps the throttle and '
            f'sends readings to tools/telemetry_logger.py on port {options.get("port", PORT)}." width="{WIDTH}" '
            f'length="{LENGTH}" id_counter="10" id_counter_node="{len(NODES)}"><nodes>{nodes}</nodes>'
            f"<group><data><inputs/><outputs/></data><components>{inner}</components>"
            f"<components_bridge>{bridge}</components_bridge><groups/></group></microprocessor_definition>")


def controller(origin, run, Q=((1, 0, 0), (0, 1, 0), (0, 0, 1)), color="C2C3C7", **options):
    """A placed telemetry microcontroller (raw XML, so its ports come from its own definition)."""
    from . import definitions  # noqa: PLC0415
    from .pieces import Piece, Placed, r_attr  # noqa: PLC0415
    base = definitions.load("microprocessor")
    if base is None:
        raise ValueError(definitions.unavailable("microprocessor"))
    cells = tuple((x, 0, z) for x in range(WIDTH) for z in range(LENGTH))
    vp = "".join(f' {a}="{v}"' for a, v in zip("xyz", origin) if v)
    surfaces = 2 * WIDTH * LENGTH + 2 * (WIDTH + LENGTH)  # every outer face: a saved 4x1 writes sc="18"
    piece = Piece("microprocessor", surfaces, base.mass, cells, base.verts, base.faces)
    raw = (f'<c d="microprocessor"><o r="{r_attr(Q)}" sc="{surfaces},' + ",".join([color] * surfaces) + '">'
           f'{definition_xml(run, **options)}'
           f'<vp{vp}/><logic_slots>' + "<slot/>" * len(NODES) + "</logic_slots></o></c>")
    return Placed(piece, origin, Q, color, f"telemetry:{run}", f"engine telemetry {run}", raw_xml=raw)
