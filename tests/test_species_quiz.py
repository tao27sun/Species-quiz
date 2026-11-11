from collections import Counter
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree as ET

from openpyxl import Workbook
from PIL import Image

from app import ROOT, LocalServer, create_app, main
from species_quiz.excel_loader import WorkbookError, load_species
from species_quiz.models import SpeciesImage, SpeciesQuestion
from species_quiz.quiz import Quiz, QuizError


S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
D = "http://schemas.microsoft.com/office/spreadsheetml/2017/richdata"
L = "http://schemas.microsoft.com/office/spreadsheetml/2022/richvaluerel"


def png(color="green", format="PNG"):
    output = BytesIO()
    Image.new("RGB", (20, 30), color).save(output, format)
    return output.getvalue()


def fixture(path, names=None, cells=None, header=False, corrupt=None):
    """Small OOXML workbook with deliberately permuted indices and part names."""
    names = names if names is not None else {1: "metsäkuusi", 3: "valkoinen lumme"}
    cells = cells if cells is not None else {"B1": 0, "C1": 1, "AA1": 2, "B3": 0}
    wb = Workbook()
    ws = wb.active
    ws.title = "Plants renamed"
    for row, name in names.items():
        ws.cell(row, 1, name)
    if header:
        header_name = "芬兰语名称" if header is True else header
        for col, value in enumerate([header_name, "图片1", "图片2", "图片3"], 1):
            ws.cell(1, col, value)
    for coordinate in cells:
        ws[coordinate] = "#VALUE!"
    other = wb.create_sheet("Ignored")
    other["A1"] = "No image on this sheet"
    memory = BytesIO()
    wb.save(memory)
    with zipfile.ZipFile(memory) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    sheet = ET.fromstring(parts.pop("xl/worksheets/sheet1.xml"))
    for cell in sheet.findall(".//{*}c"):
        if cell.get("r") in cells:
            cell.set("vm", str(cells[cell.get("r")] + 1))
    if corrupt == "index":
        next(c for c in sheet.findall(".//{*}c") if c.get("vm")).set("vm", "0")
    if corrupt == "missing_vm":
        del next(c for c in sheet.findall(".//{*}c") if c.get("vm")).attrib["vm"]
    parts["xl/worksheets/plants-renamed.xml"] = ET.tostring(sheet)
    rels = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
    for rel in rels:
        if rel.get("Target", "").endswith("sheet1.xml"):
            rel.set("Target", "worksheets/plants-renamed.xml")
    for i, (kind, target) in enumerate([
        ("sheetMetadata", "meta-renamed.xml"), ("rdRichValue", "richData/values-renamed.xml"),
        ("rdRichValueStructure", "richData/structure-renamed.xml"), ("richValueRel", "richData/links-renamed.xml")
    ]):
        ET.SubElement(rels, f"{{{P}}}Relationship", Id=f"metadata-{i}", Type=f"{R}/{kind}", Target=target)
    parts["xl/_rels/workbook.xml.rels"] = ET.tostring(rels)
    types = f'<metadataTypes count="2"><metadataType name="UNUSED"/><metadataType name="XLRICHVALUE"/></metadataTypes>'
    future = '<futureMetadata name="XLRICHVALUE" count="3">' + ''.join(
        f'<bk><extLst><ext uri="test"><rd:rvb i="{i}"/></ext></extLst></bk>' for i in [1, 2, 0]) + '</futureMetadata>'
    values = '<valueMetadata count="3">' + ''.join(f'<bk><rc t="2" v="{i}"/></bk>' for i in [2, 0, 1]) + '</valueMetadata>'
    parts["xl/meta-renamed.xml"] = f'<metadata xmlns="{S}" xmlns:rd="{D}">{types}{future}{values}</metadata>'.encode()
    # The image identifier is the SECOND field, and all relation IDs are arbitrary.
    parts["xl/richData/structure-renamed.xml"] = f'<rvStructures xmlns="{D}"><s t="_localImage"><k n="CalcOrigin"/><k n="_rvRel:LocalImageIdentifier"/></s></rvStructures>'.encode()
    parts["xl/richData/values-renamed.xml"] = (f'<rvData xmlns="{D}">' + ''.join(f'<rv s="0"><v>5</v><v>{i}</v></rv>' for i in [2, 0, 1]) + '</rvData>').encode()
    parts["xl/richData/links-renamed.xml"] = f'<richValueRels xmlns="{L}" xmlns:r="{R}"><rel r:id="green"/><rel r:id="blue"/><rel r:id="red"/></richValueRels>'.encode()
    parts["xl/richData/_rels/links-renamed.xml.rels"] = (f'<Relationships xmlns="{P}">' + ''.join(
        f'<Relationship Id="{color}" Type="{R}/image" Target="../media/{color}-asset.bin"/>' for color in ["blue", "red", "green"]) + '</Relationships>').encode()
    for color in ["red", "green", "blue"]:
        parts[f"xl/media/{color}-asset.bin"] = png(color, "BMP" if color == "blue" else "PNG")
    if corrupt == "image":
        parts["xl/media/red-asset.bin"] = b"broken"
    if corrupt == "relationship":
        del parts["xl/media/red-asset.bin"]
    if corrupt == "metadata":
        del parts["xl/meta-renamed.xml"]
    with zipfile.ZipFile(path, "w") as output:
        for name, data in parts.items():
            output.writestr(name, data)


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "quiz.xlsx"

    def test_real_workbook(self):
        bank = load_species(ROOT / "quiz.xlsx")
        self.assertEqual(len(bank), 67)
        self.assertEqual(sum(len(q.images) for q in bank), 124)
        images = {image.cell: image for question in bank for image in question.images}
        self.assertEqual(len({image.data for image in images.values()}), 124)
        self.assertEqual(bank[0].row_number, 2)
        self.assertEqual(bank[-1].row_number, 68)
        # Independent XML reference walk for every cell, not just image counts.
        with zipfile.ZipFile(ROOT / "quiz.xlsx") as z:
            xml = lambda name: ET.fromstring(z.read(name))
            sheet = xml("xl/worksheets/sheet1.xml")
            metadata = xml("xl/metadata.xml")
            rich = list(xml("xl/richData/rdrichvalue.xml"))
            links = list(xml("xl/richData/richValueRel.xml"))
            rels = {r.get("Id"): r.get("Target").replace("../", "xl/") for r in xml("xl/richData/_rels/richValueRel.xml.rels")}
            for cell in sheet.findall(".//{*}c"):
                if not cell.get("vm"):
                    continue
                record = metadata.find("{*}valueMetadata")[int(cell.get("vm")) - 1][0]
                future = metadata.find("{*}futureMetadata")[int(record.get("v"))]
                rv = rich[int(future.find(".//{*}rvb").get("i"))]
                relation = links[int(rv[0].text)]
                target = rels[relation.get(f"{{{R}}}id")]
                self.assertEqual(images[cell.get("r")].data, z.read(target), cell.get("r"))

    def test_permuted_mapping_blank_row_late_column_conversion(self):
        fixture(self.path)
        bank = load_species(self.path)
        self.assertEqual([q.row_number for q in bank], [1, 3])
        self.assertEqual([i.cell for i in bank[0].images], ["B1", "C1", "AA1"])
        self.assertEqual([Image.open(BytesIO(i.data)).getpixel((0, 0)) for i in bank[0].images],
                         [(255, 0, 0), (0, 128, 0), (0, 0, 255)])
        self.assertEqual(bank[0].images[-1].mime_type, "image/png")
        self.assertEqual(bank[0].images[0].data, bank[1].images[0].data)

    def test_header_and_single_image(self):
        fixture(self.path, {2: "testspecies"}, {"B2": 0}, header=True)
        bank = load_species(self.path)
        self.assertEqual([(q.row_number, len(q.images)) for q in bank], [(2, 1)])

    def test_generic_header(self):
        fixture(self.path, {2: "testspecies"}, {"B2": 0}, header="物种名称")
        self.assertEqual(load_species(self.path)[0].name, "testspecies")

    def test_missing_image_not_silently_skipped(self):
        fixture(self.path, {2: "plant", 4: "missing"}, {"B2": 0})
        with self.assertRaisesRegex(WorkbookError, "第 4 行.*missing"):
            load_species(self.path)

    def test_arbitrary_header_not_skipped(self):
        fixture(self.path, {1: "Name", 2: "plant"}, {"B2": 0})
        with self.assertRaisesRegex(WorkbookError, "第 1 行"):
            load_species(self.path)

    def test_corruptions(self):
        for corruption in ["index", "image", "relationship", "metadata", "missing_vm"]:
            with self.subTest(corruption=corruption):
                fixture(self.path, corrupt=corruption)
                with self.assertRaisesRegex(WorkbookError, "B1|元数据"):
                    load_species(self.path)

    def test_image_only_row_is_ignored(self):
        fixture(self.path, {3: "plant"}, {"B1": 0, "B3": 1})
        self.assertEqual([q.row_number for q in load_species(self.path)], [3])

    def test_missing_invalid_empty(self):
        with self.assertRaisesRegex(WorkbookError, "找不到"):
            load_species(self.path)
        self.path.write_bytes(b"not a workbook")
        with self.assertRaises(WorkbookError):
            load_species(self.path)
        fixture(self.path, {}, {})
        with self.assertRaisesRegex(WorkbookError, "没有有效物种"):
            load_species(self.path)


def question(row=1, name="metsäkuusi"):
    return SpeciesQuestion(row, name, [SpeciesImage(f"B{row}", png(), "image/png")])


class QuizTests(unittest.TestCase):
    def test_strict_answers(self):
        for answer, expected in [("metsäkuusi", True), (" METSÄKUUSI ", True), ("metsakuusi", False),
                                 ("metsäkuus", False), ("", False), ("  ", False), ("metsä kuusi", False)]:
            with self.subTest(answer=answer):
                quiz = Quiz([question()])
                quiz.submit(quiz.round_id, 1, answer)
                self.assertEqual(quiz.state()["correct"], expected)
                self.assertEqual(quiz.state()["answer"], answer)
        for answer in ["valkoinen  lumme", "valkoinenlumme", "valkoinen-lumme"]:
            quiz = Quiz([question(name="valkoinen lumme")])
            quiz.submit(quiz.round_id, 1, answer)
            self.assertFalse(quiz.state()["correct"])

    def test_coverage_and_restart(self):
        bank = [question(i) for i in range(1, 8)]
        with patch("species_quiz.quiz.random.shuffle") as shuffle:
            quiz = Quiz(bank)
            old_round = quiz.round_id
            self.assertEqual(Counter(q.row_number for q in quiz.order), Counter(q.row_number for q in bank))
            for i in range(1, 8):
                quiz.submit(old_round, i, "METSÄKUUSI" if i % 2 else "")
                self.assertEqual(quiz.state()["status"], "ANSWERED")
                quiz.next(old_round, i)
            result = quiz.state()
            self.assertEqual((result["correct"], result["wrong"], result["accuracy"]), (4, 3, 57.1))
            self.assertEqual(len(result["mistakes"]), 3)
            quiz.restart(old_round)
            self.assertEqual(shuffle.call_count, 2)
            self.assertNotEqual(quiz.round_id, old_round)
            self.assertEqual(quiz.answers, [])
            self.assertEqual(quiz.position, 0)

    def test_invalid_transitions(self):
        quiz = Quiz([question(), question(2)])
        state = quiz.state()
        self.assertNotIn("correct_answer", state)
        with self.assertRaises(QuizError):
            quiz.next(state["round_id"], state["question_id"])
        with self.assertRaises(QuizError):
            quiz.restart(quiz.round_id)
        with self.assertRaises(QuizError):
            quiz.submit("old", state["question_id"], "answer")
        quiz.submit(state["round_id"], state["question_id"], "answer")
        with self.assertRaises(QuizError):
            quiz.submit(state["round_id"], state["question_id"], "metsäkuusi")
        quiz.next(state["round_id"], state["question_id"])
        with self.assertRaises(QuizError):
            quiz.next(state["round_id"], state["question_id"])


class AppTests(unittest.TestCase):
    def test_real_workbook_complete_round(self):
        bank = load_species(ROOT / "quiz.xlsx")
        by_row = {q.row_number: q for q in bank}
        client = create_app(questions=bank).test_client()
        state = client.get("/api/state").json
        seen = set()
        for position in range(1, len(bank) + 1):
            row = state["question_id"]
            self.assertNotIn(row, seen)
            seen.add(row)
            self.assertEqual(state["position"], position)
            self.assertEqual(len(state["images"]), len(by_row[row].images))
            for url, expected in zip(state["images"], by_row[row].images):
                response = client.get(url)
                self.assertEqual(response.data, expected.data)
            payload = state | {"answer": "  " + by_row[row].name.upper() + "  "}
            answered = client.post("/api/submit", json=payload).json
            self.assertTrue(answered["correct"])
            self.assertEqual(answered["status"], "ANSWERED")
            state = client.post("/api/next", json=payload).json
        self.assertEqual(seen, set(by_row))
        self.assertEqual((state["correct"], state["wrong"], state["accuracy"]), (len(bank), 0, 100))
        self.assertEqual(state["mistakes"], [])

    def test_api_complete_round_refresh_and_images(self):
        client = create_app(questions=[question()]).test_client()
        self.assertEqual(client.get("/").status_code, 200)
        state = client.get("/api/state").json
        self.assertNotIn("correct_answer", state)
        self.assertEqual(client.get(state["images"][0]).mimetype, "image/png")
        self.assertEqual(client.get("/images/99/0").status_code, 404)
        body = {"round_id": state["round_id"], "question_id": state["question_id"], "answer": ""}
        submitted = client.post("/api/submit", json=body)
        self.assertEqual(submitted.json["status"], "ANSWERED")
        self.assertEqual(client.get("/api/state").json, submitted.json)
        self.assertEqual(client.post("/api/submit", json=body).status_code, 409)
        result = client.post("/api/next", json=body).json
        self.assertEqual((result["correct"], result["wrong"]), (0, 1))
        self.assertEqual(result["mistakes"][0]["answer"], "")
        restart = client.post("/api/restart", json=body).json
        self.assertEqual(restart["status"], "WAITING_FOR_ANSWER")
        self.assertEqual(client.post("/api/submit", json=body).status_code, 409)
        self.assertEqual(client.post("/api/submit", json=[]).status_code, 400)

    def test_perfect_score(self):
        client = create_app(questions=[question()]).test_client()
        body = client.get("/api/state").json | {"answer": "metsäkuusi"}
        client.post("/api/submit", json=body)
        result = client.post("/api/next", json=body).json
        self.assertEqual(result["accuracy"], 100)
        self.assertEqual(result["mistakes"], [])

    def test_error_page(self):
        with patch("app.load_species", side_effect=WorkbookError("第 17 行缺图")), patch("flask.Flask.log_exception"):
            with self.assertLogs(level="ERROR"):
                client = create_app().test_client()
        response = client.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertIn("第 17 行缺图", response.get_data(as_text=True))
        self.assertNotIn("Traceback", response.get_data(as_text=True))
        self.assertEqual(client.get("/api/state").status_code, 503)

    def test_load_only_once(self):
        with patch("app.load_species", return_value=[question()]) as loader:
            client = create_app().test_client()
            body = client.get("/api/state").json | {"answer": ""}
            client.post("/api/submit", json=body)
            client.post("/api/next", json=body)
            client.post("/api/restart", json=body)
            self.assertEqual(loader.call_count, 1)

    def test_port_in_use(self):
        with patch("app.create_app"), patch("app.LocalServer", side_effect=OSError), patch("app.webbrowser.open") as browser:
            self.assertEqual(main(), 1)
            browser.assert_not_called()

    def test_exclusive_local_socket(self):
        server = LocalServer("127.0.0.1", 0, create_app(questions=[question()]))
        try:
            self.assertEqual(server.socket.getsockname()[0], "127.0.0.1")
            with self.assertRaises((OSError, SystemExit)):
                duplicate = LocalServer("127.0.0.1", server.server_port, create_app(questions=[question()]))
                duplicate.server_close()
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
