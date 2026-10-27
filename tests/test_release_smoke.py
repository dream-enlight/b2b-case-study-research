"""Public packaging checks with temporary state and no live workers/tools."""
import argparse
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile
import runner

ROOT = Path(__file__).resolve().parents[1]

class ReleaseSmokeTests(unittest.TestCase):
    def test_generic_research_routes_to_fresh_run_without_old_state(self):
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory) / "fresh-runs"
            args = argparse.Namespace(message="Research Example Company — https://company.example", id=None)
            with patch.object(runner, "RUNS", runs), patch.object(runner, "run") as execute:
                runner.app_message(args)
                state = runner.read_state(runs / "example-company")
                self.assertEqual(state["company"], "Example Company")
                self.assertEqual(state["website"], "https://company.example/")
                self.assertEqual(state["phase"], "stage1")
                self.assertEqual(state["approved_providers"], [])
                self.assertEqual(state["jobs"], {})
                self.assertTrue(state["analysis_policy"]["taxonomy_first"])
                execute.assert_called_once_with(args)

    def test_blank_seed_contains_only_the_five_headers(self):
        self.assert_seed(ROOT / "assets/case_studies_seed.xlsx")

    def assert_seed(self, path):
        ns = {"s":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(path) as archive:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            self.assertEqual([s.attrib["name"] for s in workbook.findall("s:sheets/s:sheet", ns)], ["Case studies"])
            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = ["".join(s.itertext()) for s in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            rows = sheet.findall("s:sheetData/s:row", ns)
            self.assertEqual(len(rows), 1)
            values=[]
            for cell in rows[0]:
                if cell.attrib.get("t")=="s":
                    values.append(strings[int(cell.find("s:v", ns).text)])
                elif cell.attrib.get("t")=="inlineStr":
                    values.append("".join(cell.find("s:is", ns).itertext()))
                else:
                    values.append(cell.find("s:v", ns).text)
            self.assertEqual(values, runner.HEADERS)

    def test_portable_seed_builder_has_no_external_dependency(self):
        spec=importlib.util.spec_from_file_location("public_seed_builder", ROOT / "scripts/build_seed.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"seed.xlsx";module.build(path);self.assert_seed(path)
