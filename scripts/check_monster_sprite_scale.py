#!/usr/bin/env python3
"""Find monster sprite zips with incorrect frame sizes or non-3x3 scaling.

The Digimon Database monster sprites are expected to store frames 0-14 as
48x48 PNGs made from 16x16 source sprites. Frame 15, when present, is expected
to be 96x48. In both cases, each logical pixel should be a uniform 3x3 block.
"""

from __future__ import annotations

import argparse
import csv
import io
import shutil
import struct
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable


DEFAULT_SPRITES_DIR = r"\\192.168.100.250\appdata\digimon-db\sprites\monsters"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TRANSPARENT = (0, 0, 0, 0)


@dataclass
class CheckResult:
    zip_path: Path
    frame_name: str | None = None
    frame_number: int | None = None
    width: int | None = None
    height: int | None = None
    expected_width: int | None = None
    expected_height: int | None = None
    status: str = "ok"
    details: str = ""


@dataclass
class FixResult:
    zip_path: Path
    copied_path: Path
    fixed_path: Path | None = None
    processed_path: Path | None = None
    fixed_frames: int = 0
    skipped_frames: int = 0
    details: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan monster sprite zip files and report frames with incorrect "
            "sizes or non-uniform 3x3 pixel blocks."
        )
    )
    parser.add_argument(
        "sprites_dir",
        nargs="?",
        default=DEFAULT_SPRITES_DIR,
        help=f"Folder containing monster sprite zip files. Default: {DEFAULT_SPRITES_DIR}",
    )
    parser.add_argument(
        "--expected-logical-size",
        type=int,
        default=16,
        help="Expected original sprite size before scaling. Default: 16",
    )
    parser.add_argument(
        "--expected-scale",
        type=int,
        default=3,
        help="Expected integer upscale factor. Default: 3",
    )
    parser.add_argument(
        "--skip-blocks",
        action="store_true",
        help=(
            "Only check frame dimensions. By default, the script also checks "
            "3x3 block uniformity when Pillow is installed."
        ),
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        help="Optional CSV output path for all non-ok results.",
    )
    parser.add_argument(
        "--show-ok",
        action="store_true",
        help="Print every checked zip instead of only problem zips.",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Print every problem frame instead of the default zip-level summary.",
    )
    parser.add_argument(
        "--fix-2x2",
        action="store_true",
        help=(
            "Copy non-3x3 candidate zips into a temp workspace and create fixed "
            "versions for frames that are clean 2x2 sprites. Frame 15 is copied unchanged."
        ),
    )
    parser.add_argument(
        "--fix-temp",
        default=str(Path(tempfile.gettempdir()) / "digimon_sprite_scale_fix"),
        help="Base temp folder for --fix-2x2 output.",
    )
    return parser.parse_args()


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG file")

    chunk_length = struct.unpack(">I", data[8:12])[0]
    chunk_type = data[12:16]
    if chunk_type != b"IHDR" or chunk_length < 8:
        raise ValueError("PNG is missing a valid IHDR chunk")

    width, height = struct.unpack(">II", data[16:24])
    return width, height


def numeric_png_frames(names: Iterable[str]) -> list[tuple[int, str]]:
    files = [name for name in names if not name.endswith("/")]
    frames: list[tuple[int, str]] = []
    for name in files:
        path = PurePosixPath(name)
        if path.suffix.lower() != ".png":
            continue
        try:
            frames.append((int(path.stem), name))
        except ValueError:
            continue

    return sorted(frames, key=lambda item: (item[0], item[1].count("/"), len(item[1]), item[1].lower()))


def check_uniform_blocks(data: bytes, scale: int) -> str | None:
    try:
        from PIL import Image
    except ImportError:
        return "Pillow is not installed; skipped strict block check"

    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGBA")
        width, height = image.size
        pixels = image.load()

        for y in range(0, height, scale):
            for x in range(0, width, scale):
                expected = pixels[x, y]
                for block_y in range(y, min(y + scale, height)):
                    for block_x in range(x, min(x + scale, width)):
                        if pixels[block_x, block_y] != expected:
                            return f"non-uniform {scale}x{scale} block at x={x}, y={y}"

    return None


def load_pillow_image(data: bytes):
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for --fix-2x2") from exc

    return Image.open(io.BytesIO(data)).convert("RGBA")


def image_to_png_bytes(image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def is_uniform_blocks_image(image, scale: int) -> bool:
    width, height = image.size
    if width % scale != 0 or height % scale != 0:
        return False

    pixels = image.load()
    for y in range(0, height, scale):
        for x in range(0, width, scale):
            expected = pixels[x, y]
            for block_y in range(y, y + scale):
                for block_x in range(x, x + scale):
                    if pixels[block_x, block_y] != expected:
                        return False
    return True


def collapse_blocks(image, scale: int):
    from PIL import Image

    width, height = image.size
    logical = Image.new("RGBA", (width // scale, height // scale), TRANSPARENT)
    source = image.load()
    target = logical.load()

    for y in range(logical.height):
        for x in range(logical.width):
            target[x, y] = source[x * scale, y * scale]

    return logical


def alpha_bbox(image) -> tuple[int, int, int, int] | None:
    pixels = image.load()
    left = image.width
    top = image.height
    right = -1
    bottom = -1

    for y in range(image.height):
        for x in range(image.width):
            if pixels[x, y][3] == 0:
                continue
            left = min(left, x)
            top = min(top, y)
            right = max(right, x)
            bottom = max(bottom, y)

    if right < left or bottom < top:
        return None
    return left, top, right + 1, bottom + 1


def fix_2x2_frame(data: bytes, logical_size: int, source_scale: int, target_scale: int) -> tuple[bytes, str]:
    from PIL import Image

    image = load_pillow_image(data)
    if not is_uniform_blocks_image(image, source_scale):
        raise ValueError("frame is not a clean 2x2 sprite")

    source_logical = collapse_blocks(image, source_scale)
    bbox = alpha_bbox(source_logical)
    target_logical = Image.new("RGBA", (logical_size, logical_size), TRANSPARENT)

    if bbox is not None:
        left, top, right, bottom = bbox
        crop = source_logical.crop(bbox)
        source_logical_size = source_logical.width
        ratio = logical_size / source_logical_size

        new_width = max(1, min(logical_size, round(crop.width * ratio)))
        new_height = max(1, min(logical_size, round(crop.height * ratio)))
        resized = crop.resize((new_width, new_height), Image.Resampling.NEAREST)

        source_bottom_margin = source_logical.height - bottom
        x = round(left * ratio)
        y = logical_size - round(source_bottom_margin * ratio) - new_height

        x = max(0, min(logical_size - new_width, x))
        y = max(0, min(logical_size - new_height, y))
        target_logical.alpha_composite(resized, (x, y))

        detail = (
            f"2x2 bbox {crop.width}x{crop.height}+{left}+{top} -> "
            f"{new_width}x{new_height}+{x}+{y}"
        )
    else:
        detail = "transparent frame"

    fixed = target_logical.resize((logical_size * target_scale, logical_size * target_scale), Image.Resampling.NEAREST)
    return image_to_png_bytes(fixed), detail


def frame_number_from_name(name: str) -> int | None:
    path = PurePosixPath(name)
    if path.suffix.lower() != ".png":
        return None
    try:
        return int(path.stem)
    except ValueError:
        return None


def clone_zip_info(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    cloned = zipfile.ZipInfo(info.filename, info.date_time)
    cloned.comment = info.comment
    cloned.extra = info.extra
    cloned.internal_attr = info.internal_attr
    cloned.external_attr = info.external_attr
    cloned.create_system = info.create_system
    cloned.compress_type = info.compress_type
    return cloned


def make_fix_workspace(base_dir: Path) -> tuple[Path, Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workspace = base_dir / f"monster_sprite_fix_{timestamp}"
    fixed_dir = workspace / "fixed"
    processed_dir = workspace / "processed"
    fixed_dir.mkdir(parents=True, exist_ok=False)
    processed_dir.mkdir(parents=True, exist_ok=False)
    return workspace, fixed_dir, processed_dir


def repair_zip_copy(
    copied_zip: Path,
    fixed_dir: Path,
    processed_dir: Path,
    logical_size: int,
    source_scale: int,
    target_scale: int,
) -> FixResult:
    fixed_zip = fixed_dir / copied_zip.name
    processed_zip = processed_dir / copied_zip.name
    fixed_frames = 0
    skipped: list[str] = []
    details: list[str] = []

    with zipfile.ZipFile(copied_zip, "r") as source, zipfile.ZipFile(fixed_zip, "w") as target:
        target.comment = source.comment

        for info in source.infolist():
            data = source.read(info.filename)
            frame_number = frame_number_from_name(info.filename)
            output_data = data

            if frame_number is not None and 0 <= frame_number <= 14:
                try:
                    image = load_pillow_image(data)
                    expected_size = logical_size * target_scale
                    if image.size == (expected_size, expected_size) and is_uniform_blocks_image(image, target_scale):
                        pass
                    elif image.size == (expected_size, expected_size):
                        output_data, detail = fix_2x2_frame(data, logical_size, source_scale, target_scale)
                        fixed_frames += 1
                        details.append(f"{info.filename}: {detail}")
                    else:
                        skipped.append(f"{info.filename}: size {image.width}x{image.height}")
                except Exception as exc:
                    skipped.append(f"{info.filename}: {exc}")

            target.writestr(clone_zip_info(info), output_data)

    if fixed_frames:
        shutil.copy2(copied_zip, processed_zip)
        return FixResult(
            zip_path=copied_zip,
            copied_path=copied_zip,
            fixed_path=fixed_zip,
            processed_path=processed_zip,
            fixed_frames=fixed_frames,
            skipped_frames=len(skipped),
            details="; ".join(details[:3] + skipped[:3]),
        )

    fixed_zip.unlink(missing_ok=True)
    return FixResult(
        zip_path=copied_zip,
        copied_path=copied_zip,
        fixed_frames=0,
        skipped_frames=len(skipped),
        details="; ".join(skipped[:6]) if skipped else "no 2x2 frames found",
    )


def write_fix_manifest(path: Path, results: list[FixResult]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["zip", "copied", "fixed", "processed", "fixed_frames", "skipped_frames", "details"])
        for result in results:
            writer.writerow(
                [
                    result.zip_path.name,
                    str(result.copied_path),
                    str(result.fixed_path or ""),
                    str(result.processed_path or ""),
                    result.fixed_frames,
                    result.skipped_frames,
                    result.details,
                ]
            )


def fix_2x2_zips(
    results: list[CheckResult],
    base_temp_dir: Path,
    logical_size: int,
    source_scale: int,
    target_scale: int,
) -> int:
    try:
        load_pillow_image(PNG_SIGNATURE + b"\x00" * 24)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        pass

    candidate_paths = sorted(
        {result.zip_path for result in results if result.status == "bad-blocks"},
        key=lambda path: path.name.lower(),
    )
    if not candidate_paths:
        print("\nNo non-3x3 candidate zips found to fix.")
        return 0

    workspace, fixed_dir, processed_dir = make_fix_workspace(base_temp_dir)
    fix_results: list[FixResult] = []

    print(f"\nFix workspace: {workspace}")
    print(f"Copying {len(candidate_paths)} candidate zips into the workspace root...")

    for zip_path in candidate_paths:
        copied_zip = workspace / zip_path.name
        shutil.copy2(zip_path, copied_zip)
        fix_results.append(
            repair_zip_copy(
                copied_zip=copied_zip,
                fixed_dir=fixed_dir,
                processed_dir=processed_dir,
                logical_size=logical_size,
                source_scale=source_scale,
                target_scale=target_scale,
            )
        )

    manifest_path = workspace / "fix_manifest.csv"
    write_fix_manifest(manifest_path, fix_results)

    fixed_count = sum(1 for result in fix_results if result.fixed_frames)
    fixed_frames = sum(result.fixed_frames for result in fix_results)
    skipped_frames = sum(result.skipped_frames for result in fix_results)

    print(
        f"Fix pass complete: {fixed_count} zips fixed, {fixed_frames} frames converted, "
        f"{skipped_frames} frames skipped."
    )
    print(f"Original copies: {workspace}")
    print(f"Fixed zips:      {fixed_dir}")
    print(f"Processed zips:  {processed_dir}")
    print(f"Manifest:        {manifest_path}")
    return 1 if fixed_count == 0 else 0


def expected_frame_size(frame_number: int, logical_size: int, scale: int) -> tuple[int, int] | None:
    if 0 <= frame_number <= 14:
        size = logical_size * scale
        return size, size
    if frame_number == 15:
        return logical_size * scale * 2, logical_size * scale
    return None


def make_result(
    zip_path: Path,
    frame_name: str | None,
    frame_number: int | None,
    status: str,
    details: str,
    width: int | None = None,
    height: int | None = None,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> CheckResult:
    return CheckResult(
        zip_path=zip_path,
        frame_name=frame_name,
        frame_number=frame_number,
        width=width,
        height=height,
        expected_width=expected_width,
        expected_height=expected_height,
        status=status,
        details=details,
    )


def check_zip(
    zip_path: Path,
    expected_logical_size: int,
    expected_scale: int,
    check_blocks: bool,
) -> list[CheckResult]:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            frames = numeric_png_frames(archive.namelist())
            if not frames:
                return [make_result(zip_path, None, None, "missing-frames", "no numeric PNG frames found")]

            results: list[CheckResult] = []
            for frame_number, frame_name in frames:
                expected_size = expected_frame_size(frame_number, expected_logical_size, expected_scale)
                if expected_size is None:
                    results.append(
                        make_result(zip_path, frame_name, frame_number, "unexpected-frame", "expected frames 0-15")
                    )
                    continue

                data = archive.read(frame_name)
                expected_width, expected_height = expected_size

                try:
                    width, height = png_size(data)
                except ValueError as exc:
                    results.append(make_result(zip_path, frame_name, frame_number, "bad-png", str(exc)))
                    continue

                if width != expected_width or height != expected_height:
                    results.append(
                        make_result(
                            zip_path,
                            frame_name,
                            frame_number,
                            "bad-size",
                            "incorrect sprite size",
                            width,
                            height,
                            expected_width,
                            expected_height,
                        )
                    )
                    continue

                if check_blocks:
                    block_error = check_uniform_blocks(data, expected_scale)
                    if block_error and block_error.startswith("Pillow"):
                        results.append(make_result(zip_path, frame_name, frame_number, "warning", block_error))
                        check_blocks = False
                        continue
                    if block_error:
                        results.append(
                            make_result(
                                zip_path,
                                frame_name,
                                frame_number,
                                "bad-blocks",
                                block_error,
                                width,
                                height,
                                expected_width,
                                expected_height,
                            )
                        )
                        continue

                results.append(
                    make_result(
                        zip_path,
                        frame_name,
                        frame_number,
                        "ok",
                        "",
                        width,
                        height,
                        expected_width,
                        expected_height,
                    )
                )

            return results
    except zipfile.BadZipFile:
        return [make_result(zip_path, None, None, "bad-zip", "could not read zip file")]
    except OSError as exc:
        return [make_result(zip_path, None, None, "read-error", str(exc))]


def format_size(result: CheckResult) -> str:
    if result.width is None or result.height is None:
        return "-"
    return f"{result.width}x{result.height}"


def format_expected(result: CheckResult) -> str:
    if result.expected_width is None or result.expected_height is None:
        return "-"
    return f"{result.expected_width}x{result.expected_height}"


def print_detailed_results(printable: list[CheckResult]) -> None:
    name_width = min(
        max(len(result.zip_path.name) for result in printable),
        56,
    )
    print(f"{'status':<16} {'frame':<20} {'size':<9} {'expected':<9} {'zip':<{name_width}} details")
    print(f"{'-' * 16} {'-' * 20} {'-' * 9} {'-' * 9} {'-' * name_width} {'-' * 7}")

    for result in printable:
        zip_name = result.zip_path.name
        if len(zip_name) > name_width:
            zip_name = zip_name[: name_width - 1] + "~"

        frame_name = result.frame_name or "-"
        if len(frame_name) > 20:
            frame_name = frame_name[:19] + "~"

        print(
            f"{result.status:<16} {frame_name:<20} {format_size(result):<9} "
            f"{format_expected(result):<9} {zip_name:<{name_width}} {result.details}"
        )


def print_zip_summary(printable: list[CheckResult]) -> None:
    grouped: dict[Path, list[CheckResult]] = {}
    for result in printable:
        grouped.setdefault(result.zip_path, []).append(result)

    name_width = min(max(len(path.name) for path in grouped), 56)
    print(f"{'zip':<{name_width}} {'issues':<6} {'statuses':<24} example")
    print(f"{'-' * name_width} {'-' * 6} {'-' * 24} {'-' * 7}")

    for zip_path in sorted(grouped, key=lambda path: path.name.lower()):
        zip_name = zip_path.name
        if len(zip_name) > name_width:
            zip_name = zip_name[: name_width - 1] + "~"

        zip_results = grouped[zip_path]
        status_counts: dict[str, int] = {}
        for result in zip_results:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1

        statuses = ", ".join(f"{status}:{count}" for status, count in sorted(status_counts.items()))
        if len(statuses) > 24:
            statuses = statuses[:23] + "~"

        example = zip_results[0]
        frame = example.frame_name or "-"
        detail = f"{frame} {format_size(example)}"
        if example.expected_width and example.expected_height:
            detail += f", expected {format_expected(example)}"
        if example.details:
            detail += f"; {example.details}"

        print(f"{zip_name:<{name_width}} {len(zip_results):<6} {statuses:<24} {detail}")


def print_results(results: list[CheckResult], show_ok: bool, details: bool) -> None:
    printable = results if show_ok else [result for result in results if result.status != "ok"]

    if not printable:
        print("No incorrect frame sizes or non-3x3 sprites found.")
        return

    if details:
        print_detailed_results(printable)
    else:
        print_zip_summary(printable)


def write_csv(path: Path, results: list[CheckResult]) -> None:
    problem_results = [result for result in results if result.status != "ok"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["status", "zip", "frame", "width", "height", "expected_width", "expected_height", "details"])
        for result in problem_results:
            writer.writerow(
                [
                    result.status,
                    str(result.zip_path),
                    result.frame_name or "",
                    result.width or "",
                    result.height or "",
                    result.expected_width or "",
                    result.expected_height or "",
                    result.details,
                ]
            )


def main() -> int:
    configure_console()
    args = parse_args()
    sprites_dir = Path(args.sprites_dir)

    if not sprites_dir.exists():
        print(f"Sprite directory not found: {sprites_dir}", file=sys.stderr)
        return 2
    if not sprites_dir.is_dir():
        print(f"Sprite path is not a directory: {sprites_dir}", file=sys.stderr)
        return 2

    zip_paths = sorted(sprites_dir.glob("*.zip"), key=lambda path: path.name.lower())
    if not zip_paths:
        print(f"No zip files found in: {sprites_dir}", file=sys.stderr)
        return 2

    results: list[CheckResult] = []
    for zip_path in zip_paths:
        results.extend(
            check_zip(
                zip_path=zip_path,
                expected_logical_size=args.expected_logical_size,
                expected_scale=args.expected_scale,
                check_blocks=not args.skip_blocks or args.fix_2x2,
            )
        )

    print_results(results, args.show_ok, args.details)

    if args.csv_path:
        write_csv(Path(args.csv_path), results)
        print(f"\nWrote CSV report: {args.csv_path}")

    problem_count = sum(1 for result in results if result.status not in {"ok", "warning"})
    warning_count = sum(1 for result in results if result.status == "warning")
    affected_zip_count = len({result.zip_path for result in results if result.status not in {"ok", "warning"}})
    print(
        f"\nChecked {len(zip_paths)} zips / {len(results)} reported frames: "
        f"{affected_zip_count} zips with problems, {problem_count} frame problems, {warning_count} warnings."
    )

    if args.fix_2x2:
        return fix_2x2_zips(
            results=results,
            base_temp_dir=Path(args.fix_temp),
            logical_size=args.expected_logical_size,
            source_scale=2,
            target_scale=args.expected_scale,
        )

    return 1 if problem_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
