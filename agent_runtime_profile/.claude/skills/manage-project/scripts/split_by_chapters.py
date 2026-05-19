#!/usr/bin/env python3
# ruff: noqa: I001
"""
split_by_chapters.py - 按章节批量切分 episode_N.txt

识别常见章节标题（独立单行），按每集 N 章生成 source/episode_N.txt。
第一个章节标题之前的内容视为前言/简介，不写入 episode_N.txt；正式执行时
如存在非空前言，会写入 source/preface.txt。

用法:
    # Dry run（仅预览）
    python split_by_chapters.py --source source/novel.txt --chapters-per-episode 2 --dry-run

    # 实际执行
    python split_by_chapters.py --source source/novel.txt --chapters-per-episode 2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _text_utils import count_chars


CHAPTER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("arabic_chapter", re.compile(r"^第\s*\d+\s*章.*$")),
    ("chinese_chapter", re.compile(r"^第\s*[一二三四五六七八九十百千万零〇两]+\s*章.*$")),
    ("english_chapter", re.compile(r"^chapter\s+\d+.*$", re.IGNORECASE)),
    # 纯数字章节标题风险较高：只接受 1-4 位数字开头，后面可接空白 / 点 / 顿号 / 标题。
    # 例如：01、01 重逢、001. 重逢、12、12 旧梦。
    ("number_line", re.compile(r"^\d{1,4}(?:$|[\s.．、:-].*)")),
)


def _resolve_source_in_project(arg_source: str) -> tuple[Path, Path]:
    """cwd 必须含 project.json，source 必须位于 cwd/source/ 之内。"""
    cwd = Path.cwd().resolve()
    if not (cwd / "project.json").is_file():
        print(f"❌ 必须在项目目录内运行（当前 cwd={cwd} 不含 project.json）", file=sys.stderr)
        sys.exit(1)
    source_dir_unresolved = cwd / "source"
    if source_dir_unresolved.is_symlink():
        print(
            f"❌ source/ 不能是符号链接（避免分集产物落到项目外）: {source_dir_unresolved}",
            file=sys.stderr,
        )
        sys.exit(1)
    source_dir = source_dir_unresolved.resolve()
    if not source_dir.is_dir():
        print(f"❌ 项目缺 source/ 目录: {source_dir}", file=sys.stderr)
        sys.exit(1)
    source_path = (cwd / arg_source).resolve() if not Path(arg_source).is_absolute() else Path(arg_source).resolve()
    if not source_path.is_relative_to(source_dir):
        print(f"❌ 源文件必须位于 {source_dir} 内，收到: {source_path}", file=sys.stderr)
        sys.exit(1)
    if not source_path.is_file():
        print(f"❌ 源文件不存在或不是普通文件: {source_path}", file=sys.stderr)
        sys.exit(1)
    return source_path, source_dir


def _positive_int(value: str) -> int:
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"必须是正整数，收到: {value}")
    return ivalue


def _match_chapter_title(line: str, *, max_title_len: int) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or len(stripped) > max_title_len:
        return None
    for pattern_name, pattern in CHAPTER_PATTERNS:
        if pattern.match(stripped):
            return pattern_name, stripped
    return None


def detect_chapters(
    text: str,
    *,
    max_title_len: int = 80,
    min_gap_chars: int = 300,
) -> tuple[list[dict], list[dict]]:
    """按独立单行标题识别章节。

    返回 (chapters, rejected)，chapters 中 offset 指向标题行开头。
    min_gap_chars 用于过滤正文里偶然独立出现的短行“第 X 章”等误判。
    """
    chapters: list[dict] = []
    rejected: list[dict] = []
    offset = 0
    pending_lines = text.splitlines(keepends=True)

    for line_no, line in enumerate(pending_lines, start=1):
        match = _match_chapter_title(line, max_title_len=max_title_len)
        if match is None:
            offset += len(line)
            continue

        pattern_name, title = match
        candidate = {"line": line_no, "offset": offset, "title": title, "pattern": pattern_name}
        if chapters:
            previous_offset = int(chapters[-1]["offset"])
            gap_text = text[previous_offset:offset]
            gap_chars = count_chars(gap_text)
            if gap_chars < min_gap_chars:
                rejected.append({**candidate, "reason": f"与上一章间隔过短（{gap_chars} 字）"})
                offset += len(line)
                continue
        chapters.append(candidate)
        offset += len(line)

    for index, chapter in enumerate(chapters):
        chapter["chapter_index"] = index + 1
        chapter["end_offset"] = chapters[index + 1]["offset"] if index + 1 < len(chapters) else len(text)
        body = text[int(chapter["offset"]) : int(chapter["end_offset"])]
        chapter["char_count"] = count_chars(body)

    return chapters, rejected


def build_episode_plan(chapters: list[dict], chapters_per_episode: int, *, start_episode: int = 1) -> list[dict]:
    episodes: list[dict] = []
    for chunk_index, start in enumerate(range(0, len(chapters), chapters_per_episode)):
        chunk = chapters[start : start + chapters_per_episode]
        episode_no = start_episode + chunk_index
        episodes.append(
            {
                "episode": episode_no,
                "chapters": [int(ch["chapter_index"]) for ch in chunk],
                "chapter_titles": [str(ch["title"]) for ch in chunk],
                "file": f"source/episode_{episode_no}.txt",
                "char_count": sum(int(ch["char_count"]) for ch in chunk),
                "start_offset": int(chunk[0]["offset"]),
                "end_offset": int(chunk[-1]["end_offset"]),
            }
        )
    return episodes


def _rel_to_cwd(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _preview(chapters: list[dict], episodes: list[dict], preface_text: str, source_path: Path, rejected: list[dict]) -> dict:
    return {
        "source": _rel_to_cwd(source_path),
        "chapters_count": len(chapters),
        "episodes_count": len(episodes),
        "preface_chars": count_chars(preface_text),
        "preface_output": "source/preface.txt" if preface_text.strip() else None,
        "chapters_preview": {
            "first_10": [
                {
                    "chapter": int(ch["chapter_index"]),
                    "title": ch["title"],
                    "line": ch["line"],
                    "char_count": ch["char_count"],
                    "pattern": ch["pattern"],
                }
                for ch in chapters[:10]
            ],
            "last_5": [
                {
                    "chapter": int(ch["chapter_index"]),
                    "title": ch["title"],
                    "line": ch["line"],
                    "char_count": ch["char_count"],
                    "pattern": ch["pattern"],
                }
                for ch in chapters[-5:]
            ],
        },
        "episodes": [
            {
                "episode": ep["episode"],
                "chapters": ep["chapters"],
                "chapter_titles": ep["chapter_titles"],
                "file": ep["file"],
                "char_count": ep["char_count"],
            }
            for ep in episodes
        ],
        "rejected_candidates": rejected[:20],
    }


def _write_outputs(
    *,
    text: str,
    source_dir: Path,
    preface_text: str,
    episodes: list[dict],
    overwrite: bool,
) -> None:
    output_paths = [source_dir / Path(ep["file"]).name for ep in episodes]
    if preface_text.strip():
        output_paths.append(source_dir / "preface.txt")
    output_paths.append(source_dir / "episode_index.json")

    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        rels = ", ".join(_rel_to_cwd(path) for path in existing[:10])
        more = " ..." if len(existing) > 10 else ""
        print(f"❌ 输出文件已存在，请确认后加 --overwrite 覆盖：{rels}{more}", file=sys.stderr)
        sys.exit(1)

    if preface_text.strip():
        (source_dir / "preface.txt").write_text(preface_text, encoding="utf-8")

    index_payload = []
    for ep in episodes:
        episode_text = text[int(ep["start_offset"]) : int(ep["end_offset"])]
        episode_path = source_dir / Path(ep["file"]).name
        episode_path.write_text(episode_text, encoding="utf-8")
        index_payload.append(
            {
                "episode": ep["episode"],
                "chapters": ep["chapters"],
                "chapter_titles": ep["chapter_titles"],
                "file": ep["file"],
                "char_count": ep["char_count"],
            }
        )

    (source_dir / "episode_index.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="按章节批量切分 episode_N.txt")
    parser.add_argument("--source", required=True, help="源文件路径，必须位于 source/ 内")
    parser.add_argument("--chapters-per-episode", required=True, type=_positive_int, help="每集包含几章")
    parser.add_argument("--start-episode", default=1, type=_positive_int, help="起始集数编号（默认 1）")
    parser.add_argument("--max-title-len", default=80, type=_positive_int, help="章节标题最大单行长度（默认 80）")
    parser.add_argument("--min-gap-chars", default=300, type=int, help="相邻章节最小有效字数间隔（默认 300）")
    parser.add_argument("--dry-run", action="store_true", help="仅展示识别与分集预览，不写文件")
    parser.add_argument("--overwrite", action="store_true", help="正式执行时允许覆盖已有 episode/preface/index 文件")
    args = parser.parse_args()

    if args.min_gap_chars < 0:
        print(f"❌ --min-gap-chars 不能为负数，收到: {args.min_gap_chars}", file=sys.stderr)
        sys.exit(1)

    source_path, source_dir = _resolve_source_in_project(args.source)
    text = source_path.read_text(encoding="utf-8")
    chapters, rejected = detect_chapters(text, max_title_len=args.max_title_len, min_gap_chars=args.min_gap_chars)
    if not chapters:
        print("❌ 未识别到章节标题，请改用目标字数 + 锚点切分。", file=sys.stderr)
        sys.exit(1)

    preface_text = text[: int(chapters[0]["offset"])]
    episodes = build_episode_plan(chapters, args.chapters_per_episode, start_episode=args.start_episode)
    preview = _preview(chapters, episodes, preface_text, source_path, rejected)

    print(json.dumps(preview, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("\n[Dry Run] 未写入文件。确认无误后去掉 --dry-run 参数执行。")
        return

    _write_outputs(text=text, source_dir=source_dir, preface_text=preface_text, episodes=episodes, overwrite=args.overwrite)
    print("\n已生成:")
    for ep in episodes:
        print(f"  {ep['file']}（第 {ep['chapters'][0]}-{ep['chapters'][-1]} 章，{ep['char_count']} 字）")
    if preface_text.strip():
        print(f"  source/preface.txt（{count_chars(preface_text)} 字，不进入 episode）")
    print("  source/episode_index.json")


if __name__ == "__main__":
    main()
