"""pidtwin command line: digitizer output -> plant graph.

  pidtwin build results/1.Claude_Sonnet_55.json [...]     -> <input>.graph.json per sheet (+ issues)
  pidtwin merge a.graph.json b.graph.json -o plant.graph.json
  pidtwin validate plant.graph.json
  pidtwin dexpi plant.graph.json -o plant.dexpi.xml
  pidtwin dot plant.graph.json -o plant.dot                (Graphviz topology view)

Digitizing images is separate: python -m pidtwin.digitize.pipeline (see its docstring).
"""
import argparse
import json
from pathlib import Path

from .graph.build import build_graph
from .graph.schema import Graph
from .graph.validate import summary, validate


def _stem(path):
    p = Path(path)
    return p.with_name(p.name.removesuffix(".json").removesuffix(".graph"))


def _print_issues(issues, limit=15):
    print(f"  issues: {summary(issues) or 'none'}")
    for i in [i for i in issues if i.level != "info"][:limit]:
        print(f"    {i.level:7s} {i.code:18s} {i.node or '':12s} {i.message}")


def cmd_build(a):
    for f in a.inputs:
        g = build_graph(json.loads(Path(f).read_text()), sheet=a.sheet, dashed_as_piping=a.dashed_as_piping)
        out = Path(a.output) if a.output and len(a.inputs) == 1 else Path(f"{_stem(f)}.graph.json")
        g.save(out)
        issues = validate(g)
        Path(f"{_stem(out)}.issues.json").write_text(json.dumps([i.model_dump() for i in issues], indent=2))
        print(f"{f} -> {out}: {len(g.nodes)} nodes, {len(g.edges)} edges")
        for w in g.warnings:
            print(f"  note: {w}")
        _print_issues(issues)


def cmd_merge(a):
    from .graph.merge import merge
    g = merge([Graph.load(f) for f in a.inputs])
    g.save(a.output)
    print(f"{len(a.inputs)} sheets -> {a.output}: {len(g.nodes)} nodes, {len(g.edges)} edges")
    for w in g.warnings[-10:]:
        print(f"  note: {w}")
    _print_issues(validate(g))


def cmd_validate(a):
    issues = validate(Graph.load(a.input))
    _print_issues(issues, limit=10_000)


def cmd_dexpi(a):
    from .graph.dexpi import to_proteus
    out = a.output or f"{_stem(a.input)}.dexpi.xml"
    Path(out).write_text(to_proteus(Graph.load(a.input)))
    print(f"wrote {out} (DEXPI-style Proteus XML, not schema-validated)")


def cmd_dot(a):
    from .graph.dot import to_dot
    out = a.output or f"{_stem(a.input)}.dot"
    Path(out).write_text(to_dot(Graph.load(a.input)))
    print(f"wrote {out} (render with: dot -Tsvg {out} -o {Path(out).with_suffix('.svg')})")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pidtwin", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="digitizer JSON -> plant graph per sheet")
    p.add_argument("inputs", nargs="+"); p.add_argument("-o", "--output"); p.add_argument("--sheet")
    p.add_argument("--dashed-as-piping", action="store_true",
                   help="treat dashed lines as piping (sheets whose notes say dotted lines are alternates)")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("merge", help="stitch sheet graphs into one plant graph")
    p.add_argument("inputs", nargs="+"); p.add_argument("-o", "--output", required=True)
    p.set_defaults(fn=cmd_merge)
    p = sub.add_parser("validate", help="list rule violations in a graph")
    p.add_argument("input"); p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("dexpi", help="export a graph as DEXPI-style Proteus XML")
    p.add_argument("input"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_dexpi)
    p = sub.add_parser("dot", help="export a graph as Graphviz DOT")
    p.add_argument("input"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_dot)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
