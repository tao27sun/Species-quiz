"""Read Excel Place in Cell images without relying on floating drawings."""

from io import BytesIO
from pathlib import Path
import posixpath
import zipfile
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string
from PIL import Image

from .models import PlantImage, PlantQuestion


class WorkbookError(ValueError):
    """A user-facing workbook validation error."""


class Package:
    def __init__(self, archive):
        self.archive = archive

    def xml(self, part):
        return ET.fromstring(self.archive.read(part))

    def relationships(self, part):
        folder, name = posixpath.split(part)
        rels = self.xml(posixpath.join(folder, "_rels", name + ".rels"))
        result = {}
        for rel in rels:
            if rel.get("TargetMode") == "External":
                continue
            target = rel.attrib["Target"]
            resolved = posixpath.normpath(posixpath.join(folder, target))
            if target.startswith("/"):
                resolved = target.lstrip("/")
            result[rel.attrib["Id"]] = (rel.attrib["Type"].rsplit("/", 1)[-1], resolved)
        return result


def _image_data(data):
    # Decode every image before an exam starts. PNG/JPEG retain original bytes.
    with Image.open(BytesIO(data)) as image:
        image.load()
        if image.format in ("PNG", "JPEG"):
            return data, "image/png" if image.format == "PNG" else "image/jpeg"
        output = BytesIO()
        image.convert("RGBA" if "A" in image.getbands() else "RGB").save(output, "PNG")
        return output.getvalue(), "image/png"


def _index(items, value, one_based=False):
    index = int(value) - int(one_based)
    if index < 0 or index >= len(items):
        raise ValueError("图片元数据索引超出范围")
    return items[index]


def _cell_images(package, workbook_part, worksheet_part):
    all_cells = package.xml(worksheet_part).findall(".//{*}sheetData/{*}row/{*}c")
    for cell in all_cells:
        if cell.get("t") == "e" and cell.get("vm") is None:
            raise WorkbookError(f"单元格 {cell.get('r')} 存在 Excel 错误值且缺少图片映射，请检查该单元格。")
    cells = [c for c in all_cells if c.get("vm") is not None]
    if not cells:
        return {}
    parts = {kind: part for kind, part in package.relationships(workbook_part).values()}
    try:
        metadata = package.xml(parts["sheetMetadata"])
        types = list(metadata.find("{*}metadataTypes"))
        values = list(metadata.find("{*}valueMetadata"))
        futures = {f.get("name"): list(f) for f in metadata.findall("{*}futureMetadata")}
        rich_values = list(package.xml(parts["rdRichValue"]))
        structures = list(package.xml(parts["rdRichValueStructure"]))
        image_rels = list(package.xml(parts["richValueRel"]))
        targets = package.relationships(parts["richValueRel"])
    except Exception as exc:
        raise WorkbookError("无法解析单元格内图片：缺少或损坏图片元数据。") from exc

    images, cache = {}, {}
    for cell in cells:
        coordinate = cell.attrib["r"]
        try:
            # vm and metadata type indices are 1-based; rc.v, rvb.i,
            # rich-value structure and local-image indices are 0-based.
            block = _index(values, cell.attrib["vm"], one_based=True)
            matches = []
            for record in block.findall("{*}rc"):
                kind = _index(types, record.attrib["t"], one_based=True).attrib["name"]
                if kind != "XLRICHVALUE":
                    continue
                future = _index(futures[kind], record.attrib["v"])
                rich_index = future.find(".//{*}rvb").attrib["i"]
                rich = _index(rich_values, rich_index)
                structure = _index(structures, rich.attrib["s"])
                if structure.get("t") != "_localImage":
                    raise ValueError("不是受支持的本地单元格内图片")
                keys = [key.get("n") for key in structure.findall("{*}k")]
                image_index = rich.findall("{*}v")[keys.index("_rvRel:LocalImageIdentifier")].text
                relation = _index(image_rels, image_index)
                rid = next(v for k, v in relation.attrib.items() if k.endswith("}id"))
                relation_type, media_part = targets[rid]
                if relation_type != "image":
                    raise ValueError("图片关系类型不正确")
                if media_part not in cache:
                    cache[media_part] = _image_data(package.archive.read(media_part))
                data, mime_type = cache[media_part]
                matches.append(PlantImage(coordinate, data, mime_type))
            if len(matches) != 1:
                raise ValueError("每个图片单元格必须对应一张图片")
            images[coordinate] = matches[0]
        except Exception as exc:
            raise WorkbookError(f"单元格 {coordinate} 的图片无法提取或显示：{exc}") from exc
    return images


def _is_header(row, has_images):
    values = [cell.value for cell in row]
    if has_images or not values or values[0] != "芬兰语名称":
        return False
    labels = [(i, value) for i, value in enumerate(values[1:], start=1) if value is not None]
    return bool(labels) and all(value == f"图片{i}" for i, value in labels)


def load_plants(path: Path) -> list[PlantQuestion]:
    path = Path(path)
    if not path.is_file():
        raise WorkbookError("找不到 plants.xlsx，请将题库放在程序根目录后重新启动。")
    try:
        with zipfile.ZipFile(path) as archive:
            package = Package(archive)
            # Discover the workbook and worksheet through OPC relationships.
            root_rels = ET.fromstring(archive.read("_rels/.rels"))
            workbook_part = next(r.attrib["Target"].lstrip("/") for r in root_rels
                                 if r.attrib["Type"].endswith("/officeDocument"))
            sheet = package.xml(workbook_part).find("{*}sheets/{*}sheet")
            if sheet is None:
                raise WorkbookError("plants.xlsx 中没有工作表。")
            rid = next(v for k, v in sheet.attrib.items() if k.endswith("}id"))
            kind, sheet_part = package.relationships(workbook_part)[rid]
            if kind != "worksheet":
                raise WorkbookError("第一个工作表不是普通数据工作表。")
            images = _cell_images(package, workbook_part, sheet_part)

        by_row = {}
        for coordinate, image in images.items():
            column, row_number = coordinate_from_string(coordinate)
            column_number = column_index_from_string(column)
            if column_number >= 2:
                by_row.setdefault(row_number, []).append((column_number, image))
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            worksheet = workbook.worksheets[0]
            questions, errors = [], []
            first_nonempty = True
            for row_number, row in enumerate(worksheet.iter_rows(), start=1):
                if not any(cell.value is not None for cell in row):
                    continue
                row_images = [image for _, image in sorted(by_row.get(row_number, []))]
                header = first_nonempty and _is_header(row, bool(row_images))
                first_nonempty = False
                if header:
                    continue
                name = row[0].value
                if name is None or (isinstance(name, str) and not name.strip()):
                    continue
                if not isinstance(name, str):
                    errors.append(f"第 {row_number} 行的植物名称必须为文字。")
                elif not row_images:
                    errors.append(f"第 {row_number} 行存在植物名称“{name}”，但没有找到植物图片。")
                else:
                    questions.append(PlantQuestion(row_number, name, row_images))
            if errors:
                raise WorkbookError("\n".join(errors))
            if not questions:
                raise WorkbookError("题库中没有有效植物记录，请检查 A 列名称和同行图片。")
            return questions
        finally:
            workbook.close()
    except WorkbookError:
        raise
    except Exception as exc:
        raise WorkbookError("无法打开或解析 plants.xlsx，请检查文件是否损坏、被占用或格式不受支持。") from exc
