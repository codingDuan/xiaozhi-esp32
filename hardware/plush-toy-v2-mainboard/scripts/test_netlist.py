import subprocess
import unittest
import xml.etree.ElementTree as ET

import context
import kicad_env


class NetlistRoundtripA(unittest.TestCase):
    def test_exported_netlist_matches_spec(self):
        ctx = context.load("A")
        out = ctx.build / "netlist.xml"
        ctx.build.mkdir(parents=True, exist_ok=True)
        subprocess.run([kicad_env.KICAD_CLI, "sch", "export", "netlist", "--format", "kicadxml",
                        "-o", str(out), str(ctx.sch)], check=True, capture_output=True)
        exported = {}
        for net in ET.parse(out).getroot().iter("net"):
            name = net.get("name").lstrip("/")
            exported[name] = {(n.get("ref"), n.get("pin")) for n in net.iter("node")}
        for name, ends in ctx.nets.items():
            if name.startswith("NC_"):
                continue
            with self.subTest(net=name):
                self.assertEqual(exported.get(name), set(ends))

    def test_erc_clean(self):
        ctx = context.load("A")
        ctx.build.mkdir(parents=True, exist_ok=True)
        report = ctx.build / "erc.rpt"
        result = subprocess.run([kicad_env.KICAD_CLI, "sch", "erc", "--severity-error", "--exit-code-violations",
                                 "-o", str(report), str(ctx.sch)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, report.read_text(encoding="utf-8") if report.exists() else result.stderr)


if __name__ == "__main__":
    unittest.main()
