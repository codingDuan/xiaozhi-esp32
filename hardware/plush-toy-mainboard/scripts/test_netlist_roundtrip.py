"""原理图是生成物，必须证明它和 board_spec 等价：导出网表逐网络比对，再跑 ERC。"""
import json
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import board_spec
import gen_schematic
import kicad_env


class NetlistRoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sch = gen_schematic.main()
        cls.tmp = Path(tempfile.mkdtemp())
        out = cls.tmp / "net.xml"
        subprocess.run([kicad_env.KICAD_CLI, "sch", "export", "netlist",
                        "--format", "kicadxml", "-o", str(out), str(cls.sch)],
                       check=True, capture_output=True)
        root = ET.parse(out).getroot()
        cls.refs = {c.get("ref") for c in root.iter("comp")}
        cls.exported = {}
        # 不参与比对的节点：
        #   # 开头 —— PWR_FLAG 这类只存在于原理图、不上板的虚拟符号
        #   不贴件（fitted=False）—— 原理图保留它们以便改版补焊，网表照样导出，
        #   但 board_spec.nets() 只统计实际贴装的连接
        dnp = {p.ref for p in board_spec.PARTS if not p.fitted}
        for net in root.iter("net"):
            members = sorted((n.get("ref"), n.get("pin")) for n in net.iter("node")
                             if not n.get("ref", "").startswith("#") and n.get("ref") not in dnp)
            cls.exported[net.get("name").lstrip("/")] = members

    def test_regeneration_is_byte_identical_with_unique_uuids(self):
        # 随机 uuid4 让每次跑测试都改写整个 .kicad_sch，工作区永远是脏的
        first = self.sch.read_text(encoding="utf-8")
        second = gen_schematic.main().read_text(encoding="utf-8")
        self.assertEqual(first, second)
        uuids = re.findall(r'\(uuid "([^"]+)"\)', first)
        self.assertEqual(len(uuids), len(set(uuids)))

    def test_every_part_keeps_its_reference(self):
        # 缺 instances 块时 KiCad 会把位号当成未标注，网表里全是 U?、R?
        expected = {p.ref for p in board_spec.PARTS if p.pins}
        self.assertEqual(expected - self.refs, set())

    def test_every_spec_net_exported_identically(self):
        for name, members in board_spec.nets().items():
            if name.startswith("NC_"):
                continue
            with self.subTest(net=name):
                self.assertEqual(self.exported.get(name), sorted(members))

    def test_no_extra_connections(self):
        # 反向核对：网表里任何一个真实网络都必须在 board_spec 里存在，
        # 防止标签落点重叠等原因把两个网络意外连在一起
        spec = {n for n in board_spec.nets() if not n.startswith("NC_")}
        extra = {n for n, members in self.exported.items()
                 if len(members) > 1 and not n.startswith("unconnected-") and n not in spec}
        self.assertEqual(extra, set())

    def test_erc_has_no_errors(self):
        report = self.tmp / "erc.json"
        subprocess.run([kicad_env.KICAD_CLI, "sch", "erc", "--format", "json",
                        "--severity-error", "-o", str(report), str(self.sch)],
                       check=False, capture_output=True)
        data = json.loads(report.read_text())
        violations = [(v["type"], v["description"]) for s in data["sheets"] for v in s["violations"]]
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
