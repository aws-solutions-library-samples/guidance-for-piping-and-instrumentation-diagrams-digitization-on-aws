"""Export a P&ID graph as DEXPI-style Proteus XML (DEXPI 1.3 class names, Proteus 4 element layout).

Written without a schema-validated reference implementation (pyDEXPI is AGPL-3.0), so check the
output against the DEXPI XSD / your target tool before relying on it. What is written:
- Equipment with one Nozzle per piping connection;
- one PipingNetworkSystem per line number, holding PipingNetworkSegments: each segment is a chain
  of pipes and inline components between two terminals (nozzle, tee, off-page connector, open end)
  with a Connection naming both ends;
- ProcessInstrumentationFunction per instrument, and InformationFlow per signal edge.
Geometry is not written (P&ID boxes are sheet-normalized, not drawing units).
"""
import datetime as dt
import xml.etree.ElementTree as ET
from collections import defaultdict

from .schema import PHYSICAL

INLINE = {"valve", "fitting", "instrument"}


def _chains(g):
    """Split the physical graph into chains between terminals. Returns [(start, [inline ids], end)]."""
    by_id = g.by_id()
    adj = g.adjacency(PHYSICAL)
    terminal = lambda n: by_id[n].category not in INLINE | {"pipe"} or len(adj[n]) != 2
    chains, used = [], set()
    for t in [n for n in by_id if terminal(n)]:
        for first in sorted(adj[t]):
            if (t, first) in used:
                continue
            seq, prev, cur = [], t, first
            while not terminal(cur):
                seq.append(cur)
                nxt = [x for x in adj[cur] if x != prev]
                prev, cur = cur, nxt[0]
            used |= {(t, first), (cur, prev)}
            chains.append((t, seq, cur))
    # closed loops made only of inline items have no terminal; cut them at their first item
    seen = {x for _, s, _ in chains for x in s} | {n for n in by_id if terminal(n)}
    for n in by_id:
        if n not in seen and adj[n]:
            loop, prev, cur = [n], None, n
            while True:
                nxt = sorted(x for x in adj[cur] if x != prev and x not in loop)
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
                loop.append(cur)
            seen |= set(loop)
            chains.append((n, loop[1:], n))
    return chains


def to_proteus(g, originating_system="pidtwin"):
    by_id = g.by_id()
    now = dt.datetime.now()
    root = ET.Element("PlantModel")
    ET.SubElement(root, "PlantInformation", SchemaVersion="4.1.1", OriginatingSystem=originating_system,
                  Date=now.strftime("%Y-%m-%d"), Time=now.strftime("%H:%M:%S"), Is3D="no", Units="mm",
                  Discipline="PID")
    for s in g.sheets:
        ET.SubElement(root, "Drawing", Name=str(s.get("number") or s["id"]), Type="PID",
                      Title=str(s.get("title") or ""))
    attrs = lambda n: {"ID": _xid(n.id), "ComponentClass": n.dexpi_class or "CustomPipingComponent",
                       **({"TagName": n.tag} if n.tag else {})}

    chains = _chains(g)
    nozzles = defaultdict(int)
    end_ref = {}
    for i, (a, _, b) in enumerate(chains):
        for k, t in ((0, a), (1, b)):
            if by_id[t].category == "equipment":
                nozzles[t] += 1
                end_ref[(i, k)] = f"{_xid(t)}-N{nozzles[t]}"
            else:
                end_ref[(i, k)] = _xid(t)
    for n in g.nodes:
        if n.category == "equipment":
            eq = ET.SubElement(root, "Equipment", **attrs(n))
            for k in range(1, nozzles[n.id] + 1):
                ET.SubElement(eq, "Nozzle", ID=f"{_xid(n.id)}-N{k}", ComponentClass="Nozzle")

    systems = {}
    for i, (a, seq, b) in enumerate(chains):
        lines = [by_id[x].line_number for x in seq if by_id[x].line_number] or \
                [by_id[x].line_number for x in (a, b) if by_id[x].category == "tee" and by_id[x].line_number]
        line = lines[0] if lines else None
        if line not in systems:
            systems[line] = ET.SubElement(root, "PipingNetworkSystem", ID=f"PNS{len(systems) + 1}",
                                          ComponentClass="PipingNetworkSystem")
            if line:
                ga = ET.SubElement(systems[line], "GenericAttributes", Set="DexpiAttributes")
                ET.SubElement(ga, "GenericAttribute", Name="LineNumberAssignmentClass", Value=line, Format="string")
        seg = ET.SubElement(systems[line], "PipingNetworkSegment", ID=f"PNSeg{i + 1}",
                            ComponentClass="PipingNetworkSegment")
        for x in seq:
            n = by_id[x]
            if n.category == "pipe":
                p = ET.SubElement(seg, "PipingComponent", ID=_xid(n.id), ComponentClass="Pipe")
                if n.nominal_size:
                    ET.SubElement(p, "NominalDiameter", Value=n.nominal_size.rstrip('"'), Units="in")
            elif n.category == "instrument":
                ET.SubElement(seg, "PipingComponent", **{**attrs(n), "ComponentClass": "InlinePrimaryElement"})
            else:
                ET.SubElement(seg, "PipingComponent", **attrs(n))
        ET.SubElement(seg, "Connection", FromID=end_ref[(i, 0)], ToID=end_ref[(i, 1)])
    for n in g.nodes:
        if n.category in ("tee", "offpage"):
            el = ET.SubElement(root, "PipingComponent" if n.category == "tee" else "PipeOffPageConnector", **attrs(n))
            if n.category == "offpage" and n.text:
                ET.SubElement(el, "Label", Text=n.text)
    for n in g.nodes:
        if n.category == "instrument":
            ET.SubElement(root, "ProcessInstrumentationFunction",
                          **{**attrs(n), "ID": f"{_xid(n.id)}-PIF", "ComponentClass": "ProcessInstrumentationFunction"})
    for k, e in enumerate(x for x in g.edges if x.kind == "signal"):
        ET.SubElement(root, "InformationFlow", ID=f"IF{k + 1}", ComponentClass="SignalLineFunction",
                      FromID=_xid(e.src), ToID=_xid(e.dst))
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _xid(s):
    """XML IDs must start with a letter and avoid '/', '#', quotes."""
    out = "".join(c if c.isalnum() or c in "-_." else "_" for c in s)
    return out if out[:1].isalpha() else f"X{out}"
