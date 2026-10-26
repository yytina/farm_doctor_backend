import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


IMAGE_METADATA_PATTERN = re.compile(
    r"^(?P<metadata_version>[^_]+)_"
    r"(?P<detailed_project_number>[^_]+)_"
    r"(?P<source_data_type>[^_]+)_"
    r"(?P<damage_code>[^_]+)_"
    r"(?P<crop_code>[^_]+)_"
    r"(?P<crop_part_code>[^_]+)_"
    r"(?P<growth_stage_code>[^_]+)_"
    r"(?P<damage_severity_code>[^_]+)_"
    r"(?P<collector_id>[^_]+)_"
    r"(?P<collection_date>\d{8})_"
    r"(?P<capture_order>[^_]+)_"
    r"(?P<specimen_sequence>[^.]+)$"
)


@dataclass(frozen=True)
class ImageMetadata:
    metadata_version: str
    detailed_project_number: str
    source_data_type: str
    damage_code: str
    crop_code: str
    crop_part_code: str
    growth_stage_code: str
    damage_severity_code: str
    collector_id: str
    collection_date: date
    capture_order: str
    specimen_sequence: str

    def to_database_fields(self) -> dict:
        return {
            "metadata_version": self.metadata_version,
            "detailed_project_number": self.detailed_project_number,
            "source_data_type": self.source_data_type,
            "damage_code": self.damage_code,
            "crop_code": self.crop_code,
            "crop_part_code": self.crop_part_code,
            "growth_stage_code": self.growth_stage_code,
            "damage_severity_code": self.damage_severity_code,
            "collector_id": self.collector_id,
            "collection_date": self.collection_date.isoformat(),
            "capture_order": self.capture_order,
            "specimen_sequence": self.specimen_sequence,
            "metadata_parse_status": "parsed",
            "metadata_parse_error": None,
        }


def parse_image_metadata(filename: str) -> Optional[ImageMetadata]:
    """Parse the established agricultural image filename convention."""
    stem = Path(filename).stem
    match = IMAGE_METADATA_PATTERN.fullmatch(stem)
    if not match:
        return None

    values = match.groupdict()
    try:
        values["collection_date"] = date(
            int(values["collection_date"][:4]),
            int(values["collection_date"][4:6]),
            int(values["collection_date"][6:]),
        )
    except ValueError:
        return None
    return ImageMetadata(**values)
