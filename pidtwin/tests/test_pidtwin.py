"""Run: .venv/bin/python -m unittest discover tests"""
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from pidtwin.graph.build import build_graph, parse_line_number
from pidtwin.graph.dexpi import _chains, to_proteus
from pidtwin.graph.merge import merge
from pidtwin.graph.validate import validate

# Claude Sonnet 5.5 result for samples/synthetic_pid_1001.png
SHEET = json.loads((Path(__file__).parent / "data" / "synthetic.sonnet.digitized.json").read_text())


def item(iid, x, y, **kw):
    return {"id": iid, "tag": kw.pop("tag", iid), "type": kw.pop("type", None), "bbox": [x - 2, y - 2, x + 2, y + 2], **kw}


def tiny(number="S1", line='4"-P-100', offpage_text=None):
    """Pump -> gate valve -> tee; branch 1 -> check valve -> off-page, branch 2 -> blind flange."""
    return {
        "drawing": {"number": number},
        "equipment": [item("P-101", 100, 500, type="pump")],
        "valves": [item("HV-1", 300, 500, type="gate valve"), item("CK-1", 700, 500, type="check valve")],
        "instruments": [item("PI-1", 300, 300, function="ISA bubble")],
        "fittings": [item("F1", 500, 800, tag=None, type="blind flange")],
        "offpage": [{"label": "OP1", "text": offpage_text or "TO UNIT 2", "bbox": [890, 495, 910, 505]}],
        "runs": [
            {"id": "R1", "kind": "process", "line_number": line, "items": ["P-101", "HV-1", "CK-1", "OP1"],
             "path": [[100, 500], [900, 500]]},
            {"id": "R2", "kind": "process", "line_number": None, "items": ["R1", "F1"], "path": [[500, 500], [500, 800]]},
            {"id": "R3", "kind": "signal", "line_number": None, "items": ["PI-1", "HV-1"], "path": [[300, 300], [300, 500]]},
        ],
    }


class Build(unittest.TestCase):
    def test_chain_is_cut_at_items_and_tees(self):
        g = build_graph(tiny())
        cats = [n.category for n in g.nodes]
        self.assertEqual(cats.count("tee"), 1)
        self.assertEqual(cats.count("pipe"), 5)  # P-101|HV-1|tee|CK-1|OP1 = 4, tee|F1 = 1
        proc = g.adjacency(("process",))
        tee = next(n.id for n in g.nodes if n.category == "tee")
        self.assertEqual(len(proc[tee]), 3)
        hv_side = {next(iter(proc[p] - {tee})) for p in proc[tee]}
        self.assertEqual(hv_side, {"HV-1", "CK-1", "F1"})
        self.assertTrue(any(e.kind == "signal" and {e.src, e.dst} == {"PI-1", "HV-1"} for e in g.edges))
        self.assertEqual([i.code for i in validate(g) if i.level != "info"], [])

    def test_line_attributes_and_classes(self):
        g = build_graph(tiny())
        by = g.by_id()
        self.assertEqual(by["HV-1"].dexpi_class, "GateValve")
        self.assertEqual(by["P-101"].dexpi_class, "CentrifugalPump")
        pipe = next(n for n in g.nodes if n.category == "pipe" and n.line_number)
        self.assertEqual((pipe.nominal_size, pipe.service), ('4"', "P"))
        self.assertEqual(parse_line_number('6"-DW-1865'), ('6"', "DW"))
        self.assertEqual(parse_line_number("STEAM"), (None, None))

    def test_signal_run_with_line_number_is_piping(self):
        out = tiny()
        out["runs"][1]["kind"] = "signal"
        out["runs"][1]["line_number"] = '2"-D-5'
        g = build_graph(out)
        self.assertTrue(g.adjacency(("process",))["F1"])
        self.assertTrue(any("treated as piping" in w for w in g.warnings))

    def test_validation_flags_problems(self):
        out = tiny()
        out["runs"][0]["items"] = ["P-101", "HV-1", "CK-1", "END"]  # off-page now isolated
        out["valves"].append(item("XV-9", 600, 100, type="ball valve"))
        codes = {i.code for i in validate(build_graph(out))}
        self.assertIn("isolated", codes)

    def test_unconnected_sample_point_folds_into_flange(self):
        out = tiny()
        out["fittings"] += [item("F2", 640, 497, tag=None, type="flange"), item("F3", 640, 485, tag=None, type="sample point")]
        out["runs"][0]["items"] = ["P-101", "HV-1", "F2", "CK-1", "OP1"]
        g = build_graph(out)
        by = g.by_id()
        self.assertNotIn("F3", by)
        self.assertEqual(by["F2"].type, "sample connection")

    def test_run_with_two_line_labels_is_flagged(self):
        out = tiny()
        out["lines"] = [{"line_number": '4"-P-100', "bbox": [200, 490, 240, 497]},
                        {"line_number": '4"-P-200', "bbox": [800, 490, 840, 497]}]
        flagged = [i for i in validate(build_graph(out)) if i.code == "multiple_line_numbers"]
        self.assertEqual(len(flagged), 1)
        self.assertIn("run R1 ", flagged[0].message)
        out["lines"] = out["lines"][:1]
        self.assertFalse([i for i in validate(build_graph(out)) if i.code == "multiple_line_numbers"])

    def test_sample_sheet_builds_cleanly(self):
        g = build_graph(SHEET)
        proc = g.adjacency(("process",))
        self.assertFalse([n.id for n in g.nodes if n.category == "pipe" and len(proc[n.id]) != 2])
        self.assertFalse([n.id for n in g.nodes if n.category == "tee" and len(proc[n.id]) < 3])
        self.assertGreater(sum(n.category == "pipe" for n in g.nodes), 5)


class Junctions(unittest.TestCase):
    def test_join_at_a_bare_end_is_a_bend_and_duplicate_tees_merge(self):
        out = tiny()
        # R4 ends on R1's bare end: a bend into R1, not a tee
        out["runs"][0]["items"] = ["END", "P-101", "HV-1", "CK-1", "OP1"]
        out["runs"][0]["path"] = [[50, 500], [900, 500]]
        out["valves"].append(item("XV-2", 50, 300, type="ball valve"))
        out["runs"].append({"id": "R4", "kind": "process", "items": ["XV-2", "R1"], "path": [[50, 300], [50, 501]]})
        g = build_graph(out)
        self.assertFalse([n for n in g.nodes if n.category == "end"])
        self.assertEqual(sum(n.category == "tee" for n in g.nodes), 1)  # only R2's branch
        # two runs joining R1 at the same point from different runs -> one junction
        out = tiny()
        out["runs"][1]["path"] = [[500, 500], [500, 800]]
        out["valves"].append(item("XV-3", 500, 200, type="ball valve"))
        out["runs"].append({"id": "R5", "kind": "process", "items": ["XV-3", "R2"], "path": [[500, 200], [500, 501]]})
        g = build_graph(out)
        tees = [n for n in g.nodes if n.category == "tee"]
        self.assertEqual(len(tees), 1)
        self.assertEqual(len(g.adjacency(("process",))[tees[0].id]), 4)  # a cross


    def test_bare_end_on_another_pipe_joins_it_unless_that_pipe_continues_this_one(self):
        out = tiny()
        out["valves"].append(item("XV-4", 700, 200, type="ball valve"))
        # ends 6 units short of R1 with a bare END: the trace missed the join
        out["runs"].append({"id": "R4", "kind": "process", "items": ["XV-4", "END"], "path": [[700, 200], [700, 494]]})
        g = build_graph(out)
        self.assertFalse([n for n in g.nodes if n.category == "end"])
        self.assertTrue(any("joined to it" in w for w in g.warnings))
        # R5 continues R4 from its bare end: a continuation, not a join onto R5
        out["runs"][-1]["path"] = [[700, 200], [700, 400]]
        out["runs"].append({"id": "R5", "kind": "process", "items": ["R4", "CK-1"], "path": [[700, 400], [700, 500]]})
        g = build_graph(out)
        self.assertFalse([w for w in g.warnings if "joined to it" in w])


class Merge(unittest.TestCase):
    def test_offpage_on_same_line_is_stitched(self):
        a, b = build_graph(tiny("A")), build_graph(tiny("B"))
        g = merge([a, b])
        stitched = [e for e in g.edges if e.run == "offpage"]
        self.assertEqual(len(stitched), 1)
        self.assertEqual({stitched[0].src, stitched[0].dst}, {"A/OP1", "B/OP1"})
        self.assertEqual(sum(n.category == "equipment" for n in g.nodes), 1)  # same pump tag on both sheets

    def test_repeated_label_on_one_sheet_is_not_merged(self):
        out = tiny()
        out["equipment"] += [item("STA#1", 100, 100, tag="STA"), item("STA#2", 200, 100, tag="STA")]
        g = merge([build_graph(out, sheet="A"), build_graph(out, sheet="B")])
        self.assertEqual(sum(n.tag == "STA" for n in g.nodes), 4)


class Dexpi(unittest.TestCase):
    def test_export_parses_and_covers_every_inline_item_once(self):
        g = build_graph(SHEET)
        root = ET.fromstring(to_proteus(g).split("?>", 1)[1])
        self.assertEqual(root.tag, "PlantModel")
        inline = [i for _, seq, _ in _chains(g) for i in seq]
        self.assertEqual(len(inline), len(set(inline)))
        ids = [e.get("ID") for e in root.iter() if e.get("ID")]
        self.assertEqual(len(ids), len(set(ids)))


class Dot(unittest.TestCase):
    def test_pipes_become_labelled_edges(self):
        from pidtwin.graph.dot import to_dot
        dot = to_dot(build_graph(tiny()))
        self.assertTrue(dot.startswith("graph pid {"))
        self.assertIn('label="4\\"-P-100"', dot)
        self.assertIn("style=dashed", dot)  # PI-1 signal
        self.assertNotIn('"P1"', dot)


if __name__ == "__main__":
    unittest.main()
